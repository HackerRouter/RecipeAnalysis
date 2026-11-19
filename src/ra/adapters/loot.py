"""数据包适配器：战利品表。

**语法归一见共用模块 `ra.mcshared.loot`**（物理只有一份，junction 拼进来）。
本文件只保留适配器的三项义务：逐文件产生的台账、事实的状态与 provenance。
方言判定、条件/函数归一、条目树摊平都在共用模块里。

下面再导出 `condition_type` / `normalize_conditions` / `normalize_functions` /
`walk_entry`，是为了让调用方不必知道共用模块的路径——它们就是共用模块的函数本身。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..mcshared.loot import (
    ENTRY_KINDS,
    IDENTITY_KEYS,
    condition_type,
    fact_payload,
    normalize_conditions,
    normalize_functions,
    normalize_table,
    table_id_from_file,
    walk_entry,
)
from .base import Adapter, data_root, iter_json_files, record, rel_posix
from ..probe.profile import Profile
from ..util.jsonio import read_json

FAMILY = "loot_table"

__all__ = [
    "ENTRY_KINDS",
    "IDENTITY_KEYS",
    "LootAdapter",
    "annotate_products",
    "condition_type",
    "normalize_conditions",
    "normalize_functions",
    "walk_entry",
]

# `exploration_map` 把一张空地图改写成带目的地数据的已填充地图。
# 两版的物品 id 不同：新版在数据里已经写成具体地图（`abandoned_camp_map`），
# 旧版只写 `map`，产物统一是 `filled_map`。
EXPLORATION_MAP = frozenset({"exploration_map", "minecraft:exploration_map"})
EMPTY_MAP_IDS = frozenset({"minecraft:map", "minecraft:filled_map"})


def _annotate_entry(entry: dict) -> None:
    if entry.get("kind") != "item":
        return
    for function in entry.get("functions") or ():
        if not isinstance(function, dict):
            continue
        if function.get("function") not in EXPLORATION_MAP:
            continue
        product = entry.get("name")
        if product in EMPTY_MAP_IDS:
            # 旧版写在物品名里的是 `map`；修饰后物品变成 `filled_map`
            product = "minecraft:filled_map"
        if isinstance(product, str):
            entry["product_id"] = product
        for key in ("destination", "decoration", "zoom"):
            if key in function:
                entry[f"map_{key}"] = function[key]
        return


def annotate_products(payload: dict) -> None:
    """给带 `exploration_map` 的条目补「修饰后的产物 ID」。

    `product_id` 是**修饰后**的物品身份，`name` 仍是数据里写的那一个。
    两者在旧版不同（`map` → `filled_map`），新版相同（数据里已写成具体地图），
    下游按 `product_id` 判身份即可，不必自己实现 `exploration_map` 的语义。
    """
    for pool in payload.get("pools") or ():
        if not isinstance(pool, dict):
            continue
        for entry in pool.get("entries") or ():
            if isinstance(entry, dict):
                _annotate_entry(entry)


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
        data = data_root(profile, pack_dir)
        root = data / ns / rel
        for path in iter_json_files(root):
            self._one(path, data.parent, root, store)

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

        table = normalize_table(doc, table_id_from_file(file_label))
        missing = list(table.missing)
        payload = fact_payload(table)
        annotate_products(payload)
        store.add(
            Fact(
                kind="loot_table",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=Status.PARTIAL if missing else Status.PARSED,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, missing=tuple(missing))
