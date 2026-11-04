"""数据包适配器：战利品表。

两种方言，靠键名区分（probe 已判定主方言，这里按**每个文件自身**的形状分派，
因为混用情况下少数样本必须各自解析，不能一刀切）：

| 位置 | modern（26.x） | legacy（≤1.20） |
|---|---|---|
| 函数数组 | `modifier`（对象或数组） | `functions` |
| 条件 | 单数 `condition`，可写字符串引用 predicate | 数组 `conditions` |
| 条件内类型键 | `type` | `condition` |
| 序列 | `random_sequence` 存在 | 无 |

未登记的函数/条件类型不能静默丢弃：记进 `extra.unhandled` 并列台账，
由 IR 的 `condition_kinds` 映射决定怎么处理。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "loot_table"

ENTRY_KINDS = frozenset(
    {"empty", "item", "loot_table", "dynamic", "tag", "slots", "alternatives", "sequence", "group"}
)

# 能改写产物身份的复合函数：原料之外还要保留其参数。
IDENTITY_KEYS = frozenset(
    {
        "set_components",
        "set_potion",
        "set_random_potion",
        "set_enchantments",
        "enchant_randomly",
        "enchant_with_levels",
        "copy_components",
        "set_contents",
        "set_loot_table",
        "set_stew_effect",
        "set_banner_pattern",
        "set_instrument",
        "set_fireworks",
        "exploration_map",
        "furnace_smelt",
        "set_count",
    }
)


def _local(ident: str) -> str:
    return ident.split(":", 1)[-1]


def condition_type(node: object) -> str | None:
    """取条件类型。modern 对象用 `type`，legacy 对象用 `condition`；字符串指向 predicate。"""
    if isinstance(node, str):
        return f"predicate:{_local(node)}"
    if isinstance(node, dict):
        for key in ("type", "condition"):
            value = node.get(key)
            if isinstance(value, str):
                return _local(value)
    return None


def normalize_conditions(entry: dict) -> tuple[list[dict], list[str]]:
    """把一个容器（表/池/条目）上的条件归一成列表。"""
    out: list[dict] = []
    missing: list[str] = []

    single = entry.get("condition")
    if single is not None:
        out.extend(_one_condition(single, missing))

    many = entry.get("conditions")
    if many is not None:
        if isinstance(many, list):
            for node in many:
                out.extend(_one_condition(node, missing))
        else:
            missing.append("conditions 不是数组")

    return out, missing


def _one_condition(node: object, missing: list[str]) -> list[dict]:
    kind = condition_type(node)
    if kind is None:
        missing.append(f"条件无法识别类型：{type(node).__name__}")
        return []
    if isinstance(node, str):
        return [{"type": kind, "ref": node}]
    body = {k: v for k, v in node.items() if k not in ("type", "condition")}
    return [{"type": kind, **body}]


def normalize_functions(entry: dict) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    missing: list[str] = []

    for key in ("modifier", "functions"):
        raw = entry.get(key)
        if raw is None:
            continue
        nodes = raw if isinstance(raw, list) else [raw]
        for node in nodes:
            if not isinstance(node, dict):
                missing.append(f"{key} 含非对象项")
                continue
            ident = node.get("function") or node.get("type")
            if not isinstance(ident, str):
                missing.append(f"{key} 项缺少 function/type")
                continue
            local = _local(ident)
            body = {k: v for k, v in node.items() if k not in ("function", "type")}
            out.append({"function": local, **body})
    return out, missing


def walk_entry(node: object, depth: int = 0) -> tuple[list[dict], list[str]]:
    """把条目树摊平成列表。保留父子关系靠 `path`。"""
    if depth > 8:
        return [], ["条目嵌套过深"]
    if not isinstance(node, dict):
        return [], [f"条目不是对象：{type(node).__name__}"]

    missing: list[str] = []
    ident = node.get("type")
    if not isinstance(ident, str):
        return [], ["条目缺少 type"]
    kind = _local(ident)
    if kind not in ENTRY_KINDS:
        missing.append(f"未登记的条目类型 {kind}")

    conditions, cond_missing = normalize_conditions(node)
    missing.extend(cond_missing)

    functions, fn_missing = normalize_functions(node)
    missing.extend(fn_missing)

    out: list[dict] = [
        {
            "kind": kind,
            "name": node.get("name"),
            "children": len(node.get("children") or []) if isinstance(node.get("children"), list) else 0,
            "conditions": conditions,
            "functions": functions,
            "extra": {
                key: value
                for key, value in node.items()
                if key
                not in (
                    "type",
                    "name",
                    "children",
                    "conditions",
                    "condition",
                    "functions",
                    "modifier",
                    "weight",
                    "quality",
                )
            },
        }
    ]

    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            child_rows, child_missing = walk_entry(child, depth + 1)
            out.extend(child_rows)
            missing.extend(child_missing)

    return out, missing


class LootAdapter(Adapter):
    id = "src/loot"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        claim = profile.dirs.get("loot_table")
        if claim is None:
            record(
                store,
                "data/*/loot_table",
                FAMILY,
                status=LedgerStatus.FAILED,
                error="未定位战利品表目录",
            )
            return
        ns, _, rel = claim.path.partition("/")
        root = pack_data(pack_dir) / ns / rel
        for path in iter_json_files(root):
            self._one(path, pack_dir, root, store)

    def _one(self, path: Path, pack_dir: Path, root: Path, store: FactStore) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return

        missing: list[str] = []
        table_type = doc.get("type")
        if isinstance(table_type, str):
            table_type = _local(table_type)

        # 方言按文件自身形状判定，不依赖全局主方言：混用时要各自解析
        dialect = "modern" if "random_sequence" in doc else "legacy"

        pools, pool_missing = self._pools(doc)
        missing.extend(pool_missing)

        if not pools and table_type is None:
            missing.append("既无 pools 也无 type")
        elif not pools:
            # 触发型空表（可疑方块、雕刻南瓜）是合法输入，不是缺失
            pass

        payload = {
            "type": table_type,
            "dialect": dialect,
            "pools": pools,
            "random_sequence": doc.get("random_sequence"),
            "table": _table_id(file_label),
        }

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="loot_table",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1)

    def _pools(self, doc: dict) -> tuple[list[dict], list[str]]:
        missing: list[str] = []
        raw = doc.get("pools")
        if raw is None:
            return [], missing
        if not isinstance(raw, list):
            return [], ["pools 不是数组"]

        pools: list[dict] = []
        for index, pool in enumerate(raw):
            if not isinstance(pool, dict):
                missing.append(f"pool[{index}] 不是对象")
                continue
            conditions, cond_missing = normalize_conditions(pool)
            missing.extend(f"{index}: {m}" for m in cond_missing)

            entries: list[dict] = []
            raw_entries = pool.get("entries")
            if isinstance(raw_entries, list):
                for entry in raw_entries:
                    rows, entry_missing = walk_entry(entry)
                    entries.extend(rows)
                    missing.extend(f"{index}: {m}" for m in entry_missing)
            elif raw_entries is not None:
                missing.append(f"pool[{index}].entries 不是数组")

            pools.append(
                {
                    "rolls": pool.get("rolls", 1),
                    "bonus_rolls": pool.get("bonus_rolls"),
                    "conditions": conditions,
                    "entries": entries,
                    "functions": normalize_functions(pool)[0],
                }
            )
        return pools, missing


def _table_id(file_label: str) -> str:
    """`.../data/minecraft/loot_table/blocks/stone.json` → `minecraft:blocks/stone`。"""
    marker = "/loot_table/"
    if marker in file_label:
        head, _, tail = file_label.partition(marker)
        return f"{head.rsplit('/', 1)[-1]}:{tail[:-5]}"
    marker = "/loot_tables/"
    if marker in file_label:
        head, _, tail = file_label.partition(marker)
        return f"{head.rsplit('/', 1)[-1]}:{tail[:-5]}"
    return file_label[:-5]
