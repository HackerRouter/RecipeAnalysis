"""数据包适配器：结构模板（SNBT）。

模板的第一手在服务端 jar 内层（`.nbt`），由 `inputs/structures.py` 用
`net.minecraft.data.Main --dev` 转成 `.snbt`；反编译源码树的同名副本 palette 被抹空，
只作为退回路径。无论哪种来源，适配器读到的都是**文本** SNBT，不需要 NBT 解析器。

只取四样东西：

- `data[].state` → 方块（palette 条目的引用）
- `data[].nbt.LootTable` → 方块实体承载的战利品表
- `data[].nbt.pool` → 拼图池，供 `puts`/`holds` 链使用
- `entities[]` → 内嵌实体（含装备与手上的物品）

`palette` 全空但格子非空时记 `blocks_unreadable`：那是来源缺了方块身份，
不是「结构里没有方块」。SNBT 解析失败记 `failed`，不猜。

不引第三方 NBT 库：转换交给 jar 自带的 datagen（`--dev`），适配器只读文本。
自写读取器比引入依赖便宜，且 `net.minecraft.data.Main` 已顺带做了 `DataFixTypes.STRUCTURE`
升级与 `packBlockState` 归一，那些才是不自写转换器的真正原因。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from .base import Adapter, record, rel_posix
from ..paths import pack_data

FAMILY = "template"


class SnbtError(ValueError):
    pass


class SnbtReader:
    """最小 SNBT 读取器：对象、数组、字符串、数字、布尔。

    只解析到「能当 dict / list / 标量用」为止，省略两样东西：
    一是数值的宽度与类型（`1b` / `1s` / `1f` 一律退化为 int 或 float），
    二是整型数组的类型前缀含义（`[I;` / `[L;` / `[B;` 统一当成 list），
    因为结构模板只用到方块名、物品 id 与槽位这些字符串与计数。
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def parse(self) -> object:
        value = self._value()
        self._ws()
        if self.pos != len(self.text):
            raise SnbtError(f"位置 {self.pos} 后有多余内容")
        return value

    def _ws(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def _value(self) -> object:
        self._ws()
        if self.pos >= len(self.text):
            raise SnbtError("意外结束")
        ch = self.text[self.pos]
        if ch == "{":
            return self._compound()
        if ch == "[":
            return self._list()
        if ch in "\"'":
            return self._quoted(ch)
        return self._bare()

    def _compound(self) -> dict:
        self.pos += 1  # {
        out: dict = {}
        while True:
            self._ws()
            if self.pos >= len(self.text):
                raise SnbtError("compound 未闭合")
            if self.text[self.pos] == "}":
                self.pos += 1
                return out
            key = self._key()
            self._ws()
            if self.pos >= len(self.text) or self.text[self.pos] != ":":
                raise SnbtError(f"键 {key!r} 后缺冒号")
            self.pos += 1
            out[key] = self._value()
            self._ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1

    def _list(self) -> list:
        self.pos += 1  # [
        out: list = []
        # 类型前缀如 `[I;`、`[L;`、`[B;` 只在整型数组出现，这里按通用数组处理
        if self.pos + 1 < len(self.text) and self.text[self.pos] in "ILBX" and self.text[self.pos + 1] == ";":
            self.pos += 2
        while True:
            self._ws()
            if self.pos >= len(self.text):
                raise SnbtError("list 未闭合")
            if self.text[self.pos] == "]":
                self.pos += 1
                return out
            out.append(self._value())
            self._ws()
            if self.pos < len(self.text) and self.text[self.pos] == ",":
                self.pos += 1

    def _key(self) -> str:
        self._ws()
        if self.pos < len(self.text) and self.text[self.pos] in "\"'":
            ch = self.text[self.pos]
            return str(self._quoted(ch))
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ":,{}[] \t\r\n":
            self.pos += 1
        if start == self.pos:
            raise SnbtError("空键")
        return self.text[start : self.pos]

    def _quoted(self, quote: str) -> str:
        self.pos += 1
        buf: list[str] = []
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch == "\\" and self.pos + 1 < len(self.text):
                buf.append(self.text[self.pos + 1])
                self.pos += 2
                continue
            if ch == quote:
                self.pos += 1
                return "".join(buf)
            buf.append(ch)
            self.pos += 1
        raise SnbtError("字符串未闭合")

    def _bare(self) -> object:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] not in ",}] \t\r\n":
            self.pos += 1
        token = self.text[start : self.pos]
        if not token:
            raise SnbtError("空值")
        # 数值后缀与布尔后缀都可能出现（`1b`、`false`），先去后缀再判
        lowered = token.rstrip("bBsSlLfFdD")
        if lowered in ("true", "false"):
            return lowered == "true"
        try:
            return int(lowered)
        except ValueError:
            pass
        try:
            return float(lowered)
        except ValueError:
            return token


def parse_snbt(text: str) -> object:
    return SnbtReader(text).parse()


# 方块实体 NBT 里「装着物品」的键。逐键列举而不是通配 `id`，
# 因为 `id` 在方块实体里是**方块实体类型**（`minecraft:decorated_pot`），
# 把它的值当物品会把整棵模板的方块实体都读成物品。
#
# | 键 | 载体 | 形状 |
# |---|---|---|
# | `sherds` | 饰纹陶罐 | `{back: {id: ...}, front: ...}` |
# | `Items` | 箱子 / 漏斗 / 发射器 | `[{slot, item: {id, count}}]` |
# | `item` | 物品展示框 / 盔甲架 | `{id, count}` |
# | `Book` | 讲台 | `{id: "minecraft:written_book", ...}` |
# | `RecordItem` | 唱片机 | `{id, count}` |
NBT_ITEM_KEYS = ("sherds", "Items", "item", "Book", "RecordItem")


def _nbt_items(nbt: dict) -> list[tuple[str, str]]:
    """方块实体 NBT → `[(槽位名, 物品 id)]`。只取已知键，不递归猜。"""
    out: list[tuple[str, str]] = []
    for key in NBT_ITEM_KEYS:
        node = nbt.get(key)
        if node is None:
            continue
        for slot, ident in _walk_item_slots(node, key):
            out.append((slot, ident))
    return out


def _walk_item_slots(node: object, prefix: str) -> list[tuple[str, str]]:
    """在 `sherds` / `Items` 这类容器里找 `{id: "..."}` 形态的叶子。"""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        # `{"id": "minecraft:x", ...}` 是一个物品；`{"back": {...}}` 是分槽容器
        ident = node.get("id")
        if isinstance(ident, str) and ":" in ident:
            out.append((prefix, ident))
            return out
        for key, value in node.items():
            out.extend(_walk_item_slots(value, f"{prefix}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.extend(_walk_item_slots(value, f"{prefix}[{index}]"))
    return out


class TemplateAdapter(Adapter):
    id = "src/templates"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        """读模板。第一手是 jar 内层模板经 `--dev` 转出的 SNBT。

        反编译源码树的 `.snbt` 是打包副本，26.3 的 palette 被抹成空串；该来源只在 jar 侧
        不可用时才退回，并在 profile 里留痕（见 `_probe_template_source`）。
        """
        if profile.template_source == "jar" and profile.template_root and profile.template_dir:
            data_root = Path(profile.template_root) / "data"
            input_kind = "jar"
            label_base = None  # 相对 data_root 的父目录记账
        elif profile.template_dir:
            data_root = pack_data(pack_dir)
            input_kind = "src"
            label_base = pack_dir
        else:
            record(
                store,
                "data/*/structure",
                FAMILY,
                status=LedgerStatus.FAILED,
                error="结构模板不可得（jar 内层与反编译源码树都没有）",
            )
            return

        ns, _, rel = profile.template_dir.partition("/")
        root = data_root / ns / rel
        base = label_base if label_base is not None else data_root.parent
        paths = sorted(p for p in root.rglob("*.snbt") if p.is_file())
        if not paths:
            record(
                store,
                f"{ns}/{rel}",
                FAMILY,
                status=LedgerStatus.FAILED,
                error=f"模板目录里没有 .snbt：{root}",
            )
            return
        for path in paths:
            self._one(path, base, store, input_kind)

        if input_kind == "jar":
            self._skip_source_copies(profile, pack_dir, store)

        # 汇总「普通方块身份不可读」的比例，做族级登记。
        #
        # 单个模板的 blocks 为空不能直接判异常（拼图空壳层本来就全空气），
        # 但整族全空说明来源缺了方块身份——这两种必须分清，
        # 否则下游会把「我看不到方块」读成「结构里没有方块」。
        facts = store.of_kind("template")
        if facts:
            unreadable = sum(1 for f in facts if f.payload.get("blocks_unreadable"))
            if unreadable:
                with_entities = sum(
                    1 for f in facts if f.payload.get("block_entity_ids")
                )
                store.mark_unavailable(
                    "template.blocks",
                    f"{unreadable}/{len(facts)} 个模板的普通方块身份不可读",
                    f"当前模板来源（{profile.template_source}）的 palette 全为空串，"
                    f"只有方块实体的 nbt.id 保留；其中 {with_entities} 个模板能从 nbt.id 取到"
                    "方块实体身份。普通方块（如 stone、purpur_block）的『在哪个结构里出现』不可得",
                )

    def _skip_source_copies(
        self, profile: Profile, pack_dir: Path, store: FactStore
    ) -> None:
        """jar 来源生效时，反编译源码树的同名模板逐文件登记为不参与推理。

        不静默忽略：这 1511 个文件仍然存在，只是不再作为结构事实的来源。
        """
        if not profile.template_dir_src:
            return
        s_ns, _, s_rel = profile.template_dir_src.partition("/")
        src_root = pack_data(pack_dir) / s_ns / s_rel
        for path in sorted(p for p in src_root.rglob("*.snbt") if p.is_file()):
            record(
                store,
                rel_posix(path, pack_dir),
                FAMILY,
                status=LedgerStatus.CLASSIFIED_SKIP,
                rule="结构模板改读服务端 jar 内层第一手",
            )

    def _one(self, path: Path, base: Path, store: FactStore, input_kind: str) -> None:
        file_label = rel_posix(path, base)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            doc = parse_snbt(text)
        except (OSError, SnbtError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是 compound")
            return

        missing: list[str] = []
        blocks: list[str] = []
        block_entity_ids: list[str] = []
        loot_tables: list[dict] = []
        pools: list[str] = []
        item_refs: list[dict] = []

        # 方块身份来自 `data[].state`（即 palette 条目）。第一手模板（jar 内层）
        # palette 完整；反编译源码树的 26.3 副本被抹成空串，那种情况下只有带方块实体的
        # 格子还在 `nbt.id` 里保留了身份。
        # 按解析后的 data 计数：26.3 共 1170664 个 cell，其中 5597 个带 nbt.id。
        # 两个来源必须分开记，否则下游会把「看不到」当成「没有」。
        palette = doc.get("palette")
        palette_filled = 0
        if isinstance(palette, list):
            palette_filled = sum(1 for item in palette if isinstance(item, str) and item)

        data = doc.get("data")
        if not isinstance(data, list):
            missing.append("缺少 data 数组")
            data = []
        for index, cell in enumerate(data):
            if not isinstance(cell, dict):
                missing.append(f"data[{index}] 不是 compound")
                continue
            state = cell.get("state")
            if isinstance(state, str) and state:
                blocks.append(state)
            nbt = cell.get("nbt")
            if isinstance(nbt, dict):
                cell_id = nbt.get("id")
                if isinstance(cell_id, str):
                    block_entity_ids.append(cell_id)
                table = nbt.get("LootTable")
                if isinstance(table, str):
                    loot_tables.append({"pos": cell.get("pos"), "table": table})
                pool = nbt.get("pool")
                if isinstance(pool, str):
                    pools.append(pool)
                for slot, item in _nbt_items(nbt):
                    item_refs.append(
                        {"holder": cell_id if isinstance(cell_id, str) else None, "slot": slot, "id": item}
                    )

        # palette 全空但格子非空：普通方块身份不可得。
        # 这不是解析失败，而是来源缺陷，必须显式说清。
        blocks_unreadable = bool(data) and palette_filled == 0

        entities: list[dict] = []
        raw_entities = doc.get("entities")
        if isinstance(raw_entities, list):
            for index, ent in enumerate(raw_entities):
                if not isinstance(ent, dict):
                    missing.append(f"entities[{index}] 不是 compound")
                    continue
                nbt = ent.get("nbt")
                entities.append(
                    {
                        "blockPos": ent.get("blockPos"),
                        "id": nbt.get("id") if isinstance(nbt, dict) else None,
                        "has_equipment": bool(
                            isinstance(nbt, dict)
                            and (nbt.get("ArmorItems") or nbt.get("HandItems"))
                        ),
                    }
                )

        payload = {
            "template": file_label[:-5].split("/structure/")[-1].split("/structures/")[-1],
            "size": doc.get("size"),
            "data_version": doc.get("DataVersion"),
            "palette_size": len(palette) if isinstance(palette, list) else None,
            "palette_filled": palette_filled,
            "blocks": sorted(set(blocks)),
            "block_count": len(blocks),
            "block_entity_ids": sorted(set(block_entity_ids)),
            "blocks_unreadable": blocks_unreadable,
            "loot_tables": loot_tables,
            "jigsaw_pools": pools,
            "item_refs": item_refs,
            "entities": entities,
        }

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="template",
                payload=payload,
                prov=Prov(input=input_kind, file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1)
