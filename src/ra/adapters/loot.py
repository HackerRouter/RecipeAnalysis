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
    "structure_tags",
    "resolve_destination",
    "walk_entry",
]

# `exploration_map` 把一张空地图改写成带目的地数据的已填充地图。
# 两版的物品 id 不同：新版在数据里已经写成具体地图（`abandoned_camp_map`），
# 旧版只写 `map`，产物统一是 `filled_map`。
EXPLORATION_MAP = frozenset({"exploration_map", "minecraft:exploration_map"})
EMPTY_MAP_IDS = frozenset({"minecraft:map", "minecraft:filled_map"})
# `destination` 指向的标签登记在哪个注册表。tag 事实按这个键取成员。
# 两版的注册名不同：新版是 `worldgen/structure`，旧版是
# `worldgen/configured_structure_feature`（同一个概念，改过名）。
STRUCTURE_TAGS = frozenset(
    {
        "minecraft:worldgen/structure",
        "minecraft:worldgen/configured_structure_feature",
    }
)


def structure_tags(store: FactStore) -> dict[str, tuple[str, ...]]:
    """从 `tag` 事实取「结构标签 → 直接成员」，供 `destination` 展开。

    地图的目的地写成 `#minecraft:on_abandoned_camp_bamboo_jungle` 这类标签，
    成员才是结构 id。只给标签名，下游得自己再查一遍标签；两边各实现一份，
    出现两个答案时无法判断哪个错。
    """
    tags: dict[str, tuple[str, ...]] = {}
    for fact in store.of_kind("tag"):
        payload = fact.payload
        if payload.get("registry") not in STRUCTURE_TAGS:
            continue
        tag = payload.get("tag")
        values = payload.get("values") or ()
        if not isinstance(tag, str) or not isinstance(values, list):
            continue
        tags[tag] = tuple(value for value in values if isinstance(value, str))
    return tags


def resolve_destination(
    destination: str, tags: dict[str, tuple[str, ...]]
) -> list[str]:
    """`destination` → 它指向的结构 id 列表。

    `#ns:name` 按标签展开（能嵌套，逐层进去）；不带 `#` 的已经是结构 id。
    展开不到就返回空列表——不猜一个名字：目的地缺失时把产物挂到不存在的结构上，
    比少一条关系更糟。
    """
    if not destination.startswith("#"):
        return [destination]
    found: list[str] = []
    seen: set[str] = set()
    pending = [destination[1:]]
    while pending:
        tag = pending.pop()
        if tag in seen:
            continue
        seen.add(tag)
        for value in tags.get(tag, ()):
            if value.startswith("#"):
                pending.append(value[1:])
            elif value not in found:
                found.append(value)
    return sorted(found)


def _annotate_entry(entry: dict, tags: dict[str, tuple[str, ...]]) -> bool:
    """给一条带 `exploration_map` 的条目补身份。返回「目的地不在数据里」。

    旧版的 `destination` 写在代码默认值里（序列化时与默认值相同就省略），
    数据里根本没有这个键。这种条目不猜目的地，只把计数交给调用方登记。
    """
    if entry.get("kind") != "item":
        return False
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
        destination = function.get("destination")
        if not isinstance(destination, str):
            return True
        # 目的地 → 结构：与 `product_id` 合起来就是「哪个地图指向哪个结构」。
        # 展开为空也写：空列表说明标签里没有结构，而不是没算过。
        entry["map_structures"] = resolve_destination(destination, tags)
        return False
    return False


def annotate_products(
    payload: dict, tags: dict[str, tuple[str, ...]] | None = None
) -> int:
    """给带 `exploration_map` 的条目补「修饰后的产物 ID」与它指向的结构。

    `product_id` 是**修饰后**的物品身份，`name` 仍是数据里写的那一个。
    两者在旧版不同（`map` → `filled_map`），新版相同（数据里已写成具体地图），
    下游按 `product_id` 判身份即可，不必自己实现 `exploration_map` 的语义。

    `map_destination` 是目的地标签原文，`map_structures` 是展开后的结构 id：
    只给标签名时下游要再查一次标签，两边各实现一份就会有两个答案。

    返回「目的地不在数据里」的条目数，由调用方登记。
    """
    tags = tags or {}
    missing_destination = 0
    for pool in payload.get("pools") or ():
        if not isinstance(pool, dict):
            continue
        for entry in pool.get("entries") or ():
            if isinstance(entry, dict) and _annotate_entry(entry, tags):
                missing_destination += 1
    return missing_destination


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
        # 标签由 `TagAdapter` 先跑，目的地→结构在这里一次算好
        tags = structure_tags(store)
        missing_destination = 0
        for path in iter_json_files(root):
            missing_destination += self._one(path, data.parent, root, store, tags)
        if missing_destination:
            # 旧版的 `destination` 是代码默认值，数据里省略；不猜，但要能看见
            store.extra["loot_map_destination_missing"] = missing_destination

    def _one(
        self,
        path: Path,
        pack_dir: Path,
        root: Path,
        store: FactStore,
        tags: dict[str, tuple[str, ...]],
    ) -> int:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return 0

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return 0

        table = normalize_table(doc, table_id_from_file(file_label))
        missing = list(table.missing)
        payload = fact_payload(table)
        without_destination = annotate_products(payload, tags)
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
        return without_destination
