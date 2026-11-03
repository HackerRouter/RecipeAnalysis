"""世界生成适配器。

世界生成有两种来源，probe 已判定主来源（数据包内有 `worldgen/` 就用它，
否则用运行期导出）。两版的字段差异在这里吸收：

- 26.x 的 `worldgen/feature/*.json` 就是配置本身
- 1.18.2 的 `reports/worldgen/minecraft/worldgen/configured_feature/*.json`
  外面多包一层 `{"config": {...}}`

只记语法：结构/特征的类型、要放置的方块或实体 ID、引用的模板池。
「这代表什么种子」是 IR 的 `seeds` 链接。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "worldgen"

# 特征里承载「放置/引用什么」的键。只做键名到事实的搬运，不判断语义。
# `location` 是 template_pool 与 processor_list 的拼装引用，必须取：
# 「箱子表属于哪个结构」只能靠模板与模板池的这两层引用连起来。
PLACEMENT_KEYS = {
    "state_provider": "block",
    "state": "block",
    "states": "block",
    "block_state": "block",
    "block": "block",
    "to_place": "block",
    "config": "block",
    "output_state": "block",
    "input_state": "block",
    # `blocks` 在提供者里是「随机选一个放置」的候选表：
    # `{"type": "minecraft:random_block", "blocks": "#minecraft:corals"}`、
    # `{"blocks": ["minecraft:oak_sapling", "minecraft:spruce_sapling"]}`。
    # 约束类的键（`cannot_replace`、`invalid_blocks`）名字不同，不会被这条命中。
    "blocks": "block",
    # 晶洞里成簇生长的紫水晶：`inner_placements` 是方块 id 的裸列表，
    # 不是状态对象，也没有 `state` 之类的键，全靠这个键名取。
    "inner_placements": "block",
    # 方块状态对象是 `{"Name": "minecraft:oak_leaves", "Properties": {...}}`。
    # 树叶、原木这些内联在 tree feature 里的方块就藏在这个键下。
    "Name": "block",
    "type": "entity",
    "entity": "entity",
    "entity_type": "entity",
    "feature": "feature",
    "features": "feature",
    "template": "template",
    "templates": "template",
    "template_pool": "template",
    "location": "template",
    "structure": "structure",
}

# 值是方块标签而不是方块名的键。`#minecraft:corals` 表示「从该标签里随机选一个放置」，
# 与约束类标签（`cannot_replace` 之类）不是一回事，所以逐键列举、不用后缀通配。
TAG_PLACEMENT_KEYS = frozenset({"blocks"})

# 参数型世界生成注册表：它们只提供数值/参数，本就不表达放置关系。
# 无 `type` 不代表解析不全，只代表这类资源没有产出语义。
PARAMETRIC_KINDS = frozenset(
    {
        "noise",
        "density_function",
        "noise_settings",
        "multi_noise_biome_source_parameter_list",
        "block_state_provider",
        "material_condition",
        "material_rule",
        "flat_level_generator_preset",
        "world_preset",
    }
)


class WorldgenAdapter(Adapter):
    id = "src/worldgen"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        if profile.worldgen_source == "datapack":
            self._from_datapack(profile, pack_dir, store)
            return
        if profile.worldgen_source == "reports":
            self._from_reports(profile, pack_dir, store)
            return
        record(
            store,
            "worldgen/*",
            FAMILY,
            status=LedgerStatus.FAILED,
            error="世界生成事实不可得（数据包与 reports 都没有）",
        )

    def _from_datapack(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        data_root = pack_data(pack_dir)
        for key in profile.worldgen_counts:
            ns, _, rel = key.partition("/")
            root = data_root / ns / "worldgen" / rel
            for path in iter_json_files(root):
                self._one(path, pack_dir, pack_dir, _kind_of(rel), store)

    def _from_reports(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        if profile.reports_root is None:
            return
        base = Path(profile.reports_root)
        for candidate in (
            base / "worldgen" / "minecraft" / "worldgen",
            base / "minecraft" / "worldgen",
            base / "worldgen",
        ):
            if not candidate.is_dir():
                continue
            for sub in sorted(p for p in candidate.iterdir() if p.is_dir()):
                for path in iter_json_files(sub):
                    self._one(path, pack_dir, candidate, sub.name, store)
            return

    def _one(
        self, path: Path, pack_dir: Path, base: Path, kind: str, store: FactStore
    ) -> None:
        file_label = rel_posix(path, base)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            # 密度函数允许直接写标量（`zero.json` 的内容就是 `0.0`），
            # 这是合法输入，不是解析失败。
            store.add(
                Fact(
                    kind="worldgen",
                    payload={
                        "worldgen_kind": kind,
                        "id": _id_of(file_label, base),
                        "type": None,
                        "references": [],
                        "constant": doc,
                    },
                    prov=Prov(input="src", file=file_label),
                )
            )
            record(store, file_label, FAMILY, facts=1, note="标量形态")
            return

        # 1.18.2 的报告把配置包在 `config` 里；数据包内则是平铺的
        body = doc.get("config") if isinstance(doc.get("config"), dict) else doc

        references: list[dict] = []
        _collect_refs(body, references, depth=0)
        references = _dedupe(references)

        entity = doc.get("entity") or body.get("entity")
        biome = doc.get("biome") or body.get("biome")

        payload = {
            "worldgen_kind": kind,
            "id": _id_of(file_label, base),
            "type": _local(doc.get("type")),
            "references": references,
            "entity": entity if isinstance(entity, str) else None,
            "biome": biome if isinstance(biome, (str, list)) else None,
            "config_wrapped": doc is not body,
        }

        # 结构的 `spawn_overrides` 是「结构生成什么实体」的唯一数据包来源。
        # 它与 `references` 语义不同：references 记「放置了什么方块/引用」，
        # spawns 记「会冒出什么实体」，后者是 `spawns` 链接不是 `seeds`。
        spawns = _collect_spawns(doc.get("spawn_overrides"))
        if spawns:
            payload["spawns"] = spawns

        # 参数型注册表（noise、density_function 等）本就不含放置关系，无 type 不是缺陷
        resource_only = not references and payload["type"] is None
        if resource_only:
            payload["resource_only"] = True
            if kind not in PARAMETRIC_KINDS:
                payload["expects_references"] = True

        store.add(
            Fact(kind="worldgen", payload=payload, prov=Prov(input="src", file=file_label))
        )
        record(store, file_label, FAMILY, facts=1)


def _collect_refs(node: object, out: list[dict], depth: int, limit: int = 12) -> None:
    """收集「放置了什么」的引用。浅层优先，避免把整棵树摊开。"""
    if depth > limit or len(out) > 4000:
        return
    if isinstance(node, dict):
        slot = _state_object_slot(node)
        if slot is not None:
            out.append({"slot": slot, "id": str(node.get("id") or node.get("Name"))})
        for key, value in node.items():
            slot = PLACEMENT_KEYS.get(key) or _slot_of_state_key(key) or _slot_of_entry(key, node)
            if slot and isinstance(value, str):
                if _looks_like_id(value):
                    out.append({"slot": slot, "id": value})
                elif key in TAG_PLACEMENT_KEYS and _looks_like_tag(value):
                    # `#minecraft:corals`：从标签里选一个放置。标签名本身不是方块，
                    # 交给 IR 用 tag 事实展开成成员方块——那一步是语义，不在这一层。
                    out.append({"slot": "tag", "id": _tag_name(value)})
            elif slot and isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and _looks_like_id(item):
                        out.append({"slot": slot, "id": item})
            _collect_refs(value, out, depth + 1, limit)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, out, depth + 1, limit)


def _collect_spawns(raw: object) -> list[dict]:
    """结构 JSON 的 `spawn_overrides` → `[{entity, category}]`。

    形状：

    ```json
    "spawn_overrides": {
      "monster": { "bounding_box": "piece",
                   "spawns": [{"type": "minecraft:witch", "count": 1, "weight": 1}] }
    }
    ```

    26.3 的 52 个结构文件都带这个键，但绝大多数是空对象——「结构里不额外刷怪」
    与「这个结构不存在」是两回事，所以空对象不产事实、也不记缺陷。

    只取 `type`（实体 id）与游荡类别。`count` 是数量，`weight` 是权重，
    都不影响「这个实体在这个结构里会生成」这个判断，放 meta 即可。
    """
    if not isinstance(raw, dict):
        return []
    out: list[dict] = []
    for category, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        for spawn in entry.get("spawns") or []:
            if not isinstance(spawn, dict):
                continue
            ident = spawn.get("type")
            if not isinstance(ident, str) or not _looks_like_id(ident):
                continue
            out.append({"entity": ident, "category": category})
    return out


def _dedupe(refs: list[dict]) -> list[dict]:
    """同一份 JSON 里同一个引用可能被两条路径取到（状态对象 + 键名）。

    留痕比去重更啰嗦：重复的引用只会让规则数与 `slot_counts` 虚高，
    对结论没有影响，但会掩盖真实的未知引用数，所以按原顺序去重。
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for ref in refs:
        key = (ref.get("slot"), ref.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _state_object_slot(node: dict) -> str | None:
    """方块状态对象 → `block`。

    两种写法都要认：

    - 26.x：`{"id": "minecraft:acacia_leaves", "properties": {...}}`
    - 1.18.2：`{"Name": "minecraft:acacia_leaves", "Properties": {...}}`

    **属性表不能当判据**：`{"id": "minecraft:rooted_dirt"}` 也是合法且常见的
    形态（默认状态无线属性时就不写 `properties`）。早先要求 `properties`
    同时出现，结果只取到带属性的方块——`rooted_dirt`、`azalea_leaves`
    这类整批丢失，树叶断链连带把花朵、树苗一起拖死。

    改用「键集合」判据：只含状态专有键的字典就是状态对象。
    单看 `id` 太宽（模板池、群系源也用它），所以要求除此之外没有别的键。
    """
    keys = set(node)
    if keys <= {"id", "properties"} and "id" in node:
        return "block" if _looks_like_id(str(node["id"])) else None
    if keys <= {"Name", "Properties"} and "Name" in node:
        return "block" if _looks_like_id(str(node["Name"])) else None
    return None


def _slot_of_entry(key: str, node: dict) -> str | None:
    """加权方块提供者的表项：`{"data": "minecraft:azalea_leaves", "weight": 3}`。

    只认 `data` 太宽（别的结构也用这个键名），所以要求同层有 `weight`——
    这是加权表项的形状，不是全局约定。
    """
    if key == "data" and "weight" in node:
        return "block"
    return None


def _slot_of_state_key(key: str) -> str | None:
    """`default_state`、`high_states`、`trial_spawner_state` 这类键都装方块。

    方块状态提供者用「噪声阈值选一组方块」的写法，方块散在 `default_state`、
    `high_states`、`low_states` 里。键名不固定，靠后缀识别而不是枚举——
    枚举会随版本漏（花的 8 个品种就是这么整批丢掉的）。
    """
    if key in ("state", "states"):
        return "block"
    if key.endswith("_state") or key.endswith("_states"):
        return "block"
    return None


def _looks_like_id(value: str) -> bool:
    """判断是否像注册名。`#` 开头是标签引用，不是条目。

    不能排除含 `/` 的值：模板路径就是 `minecraft:village/plains/houses/...` 这种形式，
    排除掉会把整个结构拼装链丢掉。
    """
    return ":" in value and not value.startswith("#")


def _looks_like_tag(value: str) -> bool:
    """`#minecraft:corals`。`#` 前可能有空白，也可能没有。"""
    body = value.lstrip()
    return body.startswith("#") and ":" in body


def _tag_name(value: str) -> str:
    return value.lstrip()[1:]


def _local(ident: object) -> str | None:
    if not isinstance(ident, str):
        return None
    return ident.split(":", 1)[-1]


def _kind_of(sub: str) -> str:
    return sub


def _id_of(file_label: str, base: Path) -> str:
    return file_label[:-5] if file_label.endswith(".json") else file_label
