"""数据包适配器：方块变换（`block_transformer`）。

「拿着 A 对着方块 B 用，B 变成 C」——剥皮、去蜡、耕地、铲路。这是纯生存路径，
26.3 起从代码里的静态表迁到了数据包注册表。1.18.2 无此注册表，同一语义由
`code_link` 的 `transforms_source` idiom 覆盖。

## 格式（26.3 实测）

顶层是**数组**（多数注册表是单对象，不同）：

```json
[ { "block_state_provider": {"type": "minecraft:rule_based", "rules": [...]},
    "disallowed_faces": ["down"], "item_damage_per_use": 1, "sound": "..." } ]
```

一条 `rule` 是 `{if_true, then}`：

| 位置 | 形态 | 含义 |
|---|---|---|
| `if_true.type` | `matching_blocks` + `blocks` | 源方块（恒为单个字符串，非数组） |
| | `matching_block_tag` + `tag` + 可选 `offset` | 有 `offset` 是环境前提，无 `offset` 是源方块集合 |
| | `all_of` + `predicates[]` | 多个条件同时成立 |
| `then.type` | `copy_properties` + `source{id,properties}` | 目标方块带属性 |
| | 缺省 | 目标方块 `{id, properties}` |

## 两条判据

1. **`offset` 区分源方块与环境前提**。26.3 实测 `offset` 只出现在
   `matching_block_tag(minecraft:air)` 上（3 处，恒 `[0,1,0]`），含义是「上方是空气」。
   把它当 `from` 会让「泥土 → 耕地」变成「空气 → 耕地」，路径必断。
2. **`transformer` 不是工具名**。它是注册表 ID（`minecraft:axe`）；哪把斧头
   引用哪个变形器在代码侧，属语义映射。

## 红线

字段白名单之外一律 `failed`，不静默丢弃。白名单取自实测枚举（`tools/probes/probe-block-transformer.py`），
清单即本模块的常量；识别判据见 `docs/shapes.md` 的「方块转换」一节。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, data_root, iter_json_files, record, rel_posix

FAMILY = "block_transform"
REGISTRY = "block_transformer"

# 条目级字段全集（26.3 实测 10 个条目出现过 9 种）。
ENTRY_KEYS = frozenset(
    {
        "block_state_provider",
        "item_damage_per_use",
        "sound",
        "particle",
        "update_from_neighbors",
        "transform_type",
        "disallowed_faces",
        "drop_strategy",
        "loot",
    }
)

PROVIDER_TYPES = frozenset({"minecraft:rule_based"})
RULE_KEYS = frozenset({"if_true", "then"})
PREDICATE_TYPES = frozenset(
    {"minecraft:matching_blocks", "minecraft:matching_block_tag", "minecraft:all_of"}
)
# `then` 的形态：带 type 的 copy_properties，或不带 type 的裸方块状态。
THEN_TYPES = frozenset({"minecraft:copy_properties"})


class _ShapeError(Exception):
    """格式与已知形态不符。按红线报错，不猜。"""


def _check_keys(node: dict, allowed: frozenset[str], where: str) -> None:
    unknown = set(node) - allowed
    if unknown:
        raise _ShapeError(f"{where} 出现未知字段 {sorted(unknown)}")


def _block_id(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise _ShapeError(f"{where} 应为方块 ID 字符串，实际 {type(value).__name__}")
    return f"block:{value}"


def _walk_predicate(
    pred: dict, where: str, source: list[str], soft: list[str]
) -> None:
    """把一个 predicate 归入 `source`（源方块）或 `soft`（环境前提）。

    `offset` 是关键：带 offset 的 predicate 描述的是**另一个位置**，不是被转换的方块。
    """
    if not isinstance(pred, dict):
        raise _ShapeError(f"{where} 不是对象")
    ptype = pred.get("type")
    if ptype not in PREDICATE_TYPES:
        raise _ShapeError(f"{where} 未知 predicate 类型 {ptype!r}")

    if ptype == "minecraft:all_of":
        _check_keys(pred, frozenset({"type", "predicates"}), where)
        children = pred.get("predicates")
        if not isinstance(children, list):
            raise _ShapeError(f"{where}.predicates 应为数组")
        for index, child in enumerate(children):
            _walk_predicate(child, f"{where}/predicates/{index}", source, soft)
        return

    if ptype == "minecraft:matching_blocks":
        _check_keys(pred, frozenset({"type", "blocks"}), where)
        blocks = pred.get("blocks")
        if isinstance(blocks, list):
            raise _ShapeError(
                f"{where}.blocks 是数组，实测从未出现；若出现须先确认语义"
            )
        source.append(_block_id(blocks, f"{where}.blocks"))
        return

    # matching_block_tag
    _check_keys(pred, frozenset({"type", "tag", "offset"}), where)
    tag = pred.get("tag")
    if not isinstance(tag, str):
        raise _ShapeError(f"{where}.tag 应为字符串")
    ref = f"tag:{tag}"
    offset = pred.get("offset")
    if offset is None:
        source.append(ref)
        return
    if not isinstance(offset, list) or len(offset) != 3:
        raise _ShapeError(f"{where}.offset 应为三元数组")
    if offset == [0, 1, 0]:
        soft.append(f"above={ref}")
    else:
        # 非正上方的 offset 实测未出现；照实记下，由 IR 判读
        soft.append(f"offset{offset}={ref}")


def _resolve_then(then: dict, where: str) -> tuple[str, dict]:
    """返回 `(目标方块节点 ID, 属性表)`。"""
    if not isinstance(then, dict):
        raise _ShapeError(f"{where} 不是对象")
    ttype = then.get("type")

    if ttype in THEN_TYPES:
        _check_keys(then, frozenset({"type", "source"}), where)
        source = then.get("source")
        if not isinstance(source, dict):
            raise _ShapeError(f"{where}.source 应为对象")
        _check_keys(source, frozenset({"id", "properties"}), f"{where}.source")
        props = source.get("properties")
        return _block_id(source.get("id"), f"{where}.source.id"), (
            props if isinstance(props, dict) else {}
        )

    if ttype is None:
        _check_keys(then, frozenset({"id", "properties"}), where)
        props = then.get("properties")
        return _block_id(then.get("id"), f"{where}.id"), (
            props if isinstance(props, dict) else {}
        )

    raise _ShapeError(f"{where} 未知 then 类型 {ttype!r}")


class BlockTransformerAdapter(Adapter):
    id = "src/block_transformer"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        claim = profile.dirs.get(REGISTRY)
        if claim is None:
            store.mark_unavailable(
                FAMILY,
                f"该版本数据包内无 {REGISTRY}",
                "方块变换表可能硬编码在代码侧（如 1.18.2 的 AxeItem.STRIPPABLES），"
                "需 code_link 族补录，否则剥皮/耕地/去蜡路径不可达",
            )
            return

        ns, _, rel = claim.path.partition("/")
        data = data_root(profile, pack_dir)
        root = data / ns / rel
        if not root.is_dir():
            record(
                store,
                claim.path,
                FAMILY,
                status=LedgerStatus.FAILED,
                error="探测给出的变形器目录不存在",
            )
            return

        for path in iter_json_files(root):
            self._file(path, data.parent, ns, rel, store)

    def _file(
        self, path: Path, pack_dir: Path, namespace: str, rel_root: str, store: FactStore
    ) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except Exception as exc:  # noqa: BLE001 - 解析失败要原样上报
            record(
                store,
                file_label,
                FAMILY,
                status=LedgerStatus.FAILED,
                error=f"JSON 读取失败：{exc}",
            )
            return

        if not isinstance(doc, list):
            record(
                store,
                file_label,
                FAMILY,
                status=LedgerStatus.FAILED,
                error=f"顶层应为数组，实际 {type(doc).__name__}（与多数注册表不同）",
            )
            return

        # 变形器 ID 取自注册表路径：`data/<ns>/block_transformer/axe.json` → `minecraft:axe`
        stem = path.stem
        transformer = f"{namespace}:{stem}"
        produced = 0
        problems: list[str] = []

        for entry_index, entry in enumerate(doc):
            where = f"/{entry_index}"
            if not isinstance(entry, dict):
                problems.append(f"{where} 不是对象")
                continue
            extra = set(entry) - ENTRY_KEYS
            if extra:
                problems.append(f"{where} 出现未知字段 {sorted(extra)}")
                continue
            provider = entry.get("block_state_provider")
            if not isinstance(provider, dict):
                problems.append(f"{where}.block_state_provider 缺失或不是对象")
                continue
            ptype = provider.get("type")
            if ptype not in PROVIDER_TYPES:
                problems.append(f"{where}.block_state_provider 未知类型 {ptype!r}")
                continue
            unknown = set(provider) - {"type", "rules"}
            if unknown:
                problems.append(f"{where}.block_state_provider 未知字段 {sorted(unknown)}")
                continue
            rules = provider.get("rules")
            if not isinstance(rules, list):
                problems.append(f"{where}.block_state_provider.rules 应为数组")
                continue

            for rule_index, rule in enumerate(rules):
                rule_where = f"{where}/block_state_provider/rules/{rule_index}"
                try:
                    produced += self._rule(
                        rule, rule_where, entry, transformer, file_label, store
                    )
                except _ShapeError as exc:
                    problems.append(str(exc))

        if problems:
            record(
                store,
                file_label,
                FAMILY,
                facts=produced,
                status=LedgerStatus.FAILED if produced == 0 else LedgerStatus.PARTIAL,
                error="；".join(problems[:5]) + ("…" if len(problems) > 5 else ""),
            )
        else:
            record(store, file_label, FAMILY, facts=produced)

    def _rule(
        self,
        rule: object,
        where: str,
        entry: dict,
        transformer: str,
        file_label: str,
        store: FactStore,
    ) -> int:
        if not isinstance(rule, dict):
            raise _ShapeError(f"{where} 不是对象")
        _check_keys(rule, RULE_KEYS, where)

        source: list[str] = []
        soft: list[str] = []
        _walk_predicate(rule.get("if_true"), f"{where}/if_true", source, soft)
        if not source:
            raise _ShapeError(f"{where} 没有任何源方块条件")

        target, properties = _resolve_then(rule.get("then"), f"{where}/then")

        payload: dict = {
            "transformer": transformer,
            "transformer_kind": "registry",
            "mode": "rules",
            "from": source,
            "to": target,
            "properties": properties,
            "soft": soft,
            "loot": entry.get("loot"),
            "drop_strategy": entry.get("drop_strategy"),
            "damage_per_use": entry.get("item_damage_per_use"),
            "disallowed_faces": entry.get("disallowed_faces") or [],
            "particle": entry.get("particle"),
            "sound": entry.get("sound"),
            "update_from_neighbors": bool(entry.get("update_from_neighbors", False)),
            "transform_type": entry.get("transform_type"),
        }

        store.add(
            Fact(
                kind="block_transform",
                payload=payload,
                prov=Prov(input="src", file=file_label, ptr=where),
            )
        )
        return 1
