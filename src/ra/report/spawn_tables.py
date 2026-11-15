"""刷怪表的可查表。

一行是「某处会刷某个实体，权重多少、每次几只、第几波」。五处来源形状不同，
在这里统一成同一组字段，供下游直接查：

| holder_kind | holder | 来源事实 | 含义 |
|---|---|---|---|
| `biome` | `biome:minecraft:plains` | `worldgen` 的 `spawns` | 群系自然刷怪 |
| `structure` | `structure:minecraft:fortress` | `worldgen` 的 `spawns` | 结构覆盖刷怪 |
| `trial_spawner` | `trial_spawner:minecraft:trial_chamber/breeze/normal` | `spawner_config` 的 `entities` | 试炼刷怪笼 |
| `structure_template` | `structure_template:minecraft:woodland_mansion/1x1_as2` | `template` 的 `spawner_potentials` | 模板里的刷怪笼方块 |
| `raid` | `raid:minecraft:overworld` | `code_link` 的 `raid_waves` | 袭击波次 |

只出数据包与代码写下的值，不折算概率：`weight` 是同一 `holder` + `category` 内的
相对权重，分母要由消费方按这两列分组求和；`count_min` / `count_max` 缺省记 null，
不补 1。

**波次**：只有 `raid` 有 `wave`，取值即波次号，第 0 位在代码里不被读取所以不出现。
实际打几波由难度决定（简单 3、普通 5、困难 7），另有奖励波——这层映射在
`Raid#getNumGroups`，是难度参数，下游按 `wave` 截取前 N 波即可。`count` 是基础数量，
不含 `getPotentialBonusSpawns` 的随机增量。

**前提**：`requires` 记「这一行还需要什么」。不祥试炼（`tier=ominous`）需要不祥之兆，
记为 `assume:ominous`；袭击波次记为 `assume:raid`。不祥宝库不在这张表里——它是
试炼密室的 reward 池生成的方块，开启要 `ominous_trial_key`，钥匙来自不祥配置的
`eject_tables`（见 `spawner_config` 事实），依赖链在 ADR 0013。

**不包含**由代码放置的普通刷怪笼（地牢、矿井中的 `MonsterRoomFeature` 一类）：
那些实体表写在代码的等概率数组里，不是权重表，也没有数据包痕迹。
"""

from __future__ import annotations

from ..facts import FactStore
from .structure_tables import ident_of

TABLE_SPAWNS = "spawn_tables"

COLUMNS = (
    "holder_kind",
    "holder",
    "category",
    "entity",
    "weight",
    "count_min",
    "count_max",
    "wave",
    "requires",
)

# 不祥试炼与袭击的前提节点。两者都是假设层：不判触发概率，只判「能发生」。
OMINOUS = "assume:ominous"
RAID = "assume:raid"


def _row(
    holder_kind: str,
    holder: str,
    category: str | None,
    entity: object,
    weight: object,
    low: object,
    high: object,
    *,
    wave: object = None,
    requires: str | None = None,
) -> dict | None:
    if not isinstance(entity, str) or not entity:
        return None
    return {
        "holder_kind": holder_kind,
        "holder": holder,
        "category": category,
        "entity": entity,
        "weight": weight if isinstance(weight, int) else None,
        "count_min": low if isinstance(low, int) else None,
        "count_max": high if isinstance(high, int) else None,
        "wave": wave if isinstance(wave, int) else None,
        "requires": requires,
    }


def build_spawn_tables(store: FactStore) -> dict[str, list[dict]]:
    """事实库 → `{TABLE_SPAWNS: 行}`。按 `(holder_kind, holder, wave, category, entity, weight)` 排序。"""
    rows: list[dict] = []

    for fact in store.of_kind("worldgen"):
        payload = fact.payload
        kind = payload.get("worldgen_kind")
        if kind == "biome":
            holder_kind = "biome"
        elif kind in ("structure", "configured_structure_feature"):
            holder_kind = "structure"
        else:
            continue
        ident = ident_of(payload.get("id"), kind)
        if ident is None:
            continue
        for spawn in payload.get("spawns") or []:
            if not isinstance(spawn, dict):
                continue
            row = _row(
                holder_kind,
                f"{holder_kind}:{ident}",
                spawn.get("category"),
                spawn.get("entity"),
                spawn.get("weight"),
                spawn.get("count_min"),
                spawn.get("count_max"),
            )
            if row is not None:
                rows.append(row)

    for fact in store.of_kind("spawner_config"):
        payload = fact.payload
        ident = payload.get("id")
        namespace = payload.get("namespace")
        if not isinstance(ident, str):
            continue
        holder = f"trial_spawner:{namespace}:{ident}" if isinstance(namespace, str) else f"trial_spawner:{ident}"
        # 不祥配置只有玩家带不祥之兆时才启用；`tier` 不是刷怪类别，不填进 category，
        # 它在配置 id 的最后一段，从 holder 就能读到。
        requires = OMINOUS if payload.get("tier") == "ominous" else None
        for entry in payload.get("entities") or []:
            if not isinstance(entry, dict):
                continue
            # 试炼刷怪笼的配置本身没有「每次几只」：同时存在数与总量是难度参数，
            # 不是一次刷出的数量，所以 count 留 null。
            row = _row(
                "trial_spawner",
                holder,
                None,
                entry.get("id"),
                entry.get("weight"),
                None,
                None,
                requires=requires,
            )
            if row is not None:
                rows.append(row)

    for fact in store.of_kind("template"):
        payload = fact.payload
        template = payload.get("template")
        if not isinstance(template, str):
            continue
        holder = f"structure_template:{template}"
        for entry in payload.get("spawner_potentials") or []:
            if not isinstance(entry, dict):
                continue
            row = _row(
                "structure_template",
                holder,
                None,
                entry.get("entity"),
                entry.get("weight"),
                None,
                None,
            )
            if row is not None:
                rows.append(row)

    # 袭击波次：代码里的枚举，不是数据包。一行一个（实体, 波次）。
    for fact in store.of_kind("code_link"):
        payload = fact.payload
        if payload.get("idiom") != "raid_waves":
            continue
        link = payload.get("link")
        meta = payload.get("meta")
        if not isinstance(link, dict) or not isinstance(meta, dict):
            continue
        head = link.get("head")
        if not isinstance(head, str) or not head.startswith("entity:"):
            continue
        count = meta.get("count")
        row = _row(
            "raid",
            "raid:minecraft:overworld",
            None,
            head.split(":", 1)[1],
            None,
            count,
            count,
            wave=meta.get("wave"),
            requires=RAID,
        )
        if row is not None:
            rows.append(row)

    rows.sort(
        key=lambda row: (
            row["holder_kind"],
            row["holder"],
            row["wave"] if row["wave"] is not None else -1,
            row["category"] or "",
            row["entity"],
            row["weight"] if row["weight"] is not None else -1,
        )
    )
    return {TABLE_SPAWNS: rows}
