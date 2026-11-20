"""`exploration_map` 的默认目的地：只写在源码里，补回战利品事实。

旧版战利品条目写的是空地图 + `exploration_map`，但 `destination` 被序列化省略了：
它的默认值与非默认值相同时不写进 JSON。于是数据侧看不出这张地图指向哪个结构。

默认值在 loot 函数的源码里：

```java
public static final TagKey<ConfiguredStructureFeature<?, ?>> DEFAULT_FEATURE
        = ConfiguredStructureTags.ON_TREASURE_MAPS;   // 1.18.2 ExplorationMapFunction 第 40 行

if (!explorationMapFunction.destination.equals(DEFAULT_FEATURE)) {
    jsonObject.addProperty("destination", ...);        // 第 146-147 行：等于默认就不写
}
```

所以「数据里没有 destination」本身就是一条信息：目的地是那个默认标签。补写的字段带
`map_destination_default = true`，与数据里写明的区分开——两者可信度不同，混成一个字段
就再也分不出哪条是推断。

## 为什么在这一层补

这条默认值的取证在源码侧，要改的字段在战利品事实侧。源码适配器是唯一同时拿得到
Java 源码根与全量事实的地方，所以跨族补写明确落在这里，不留给每个下游各自实现一遍。

## 不猜的条件

- 本版源码里找不到这条默认值（新版把 `destination` 改成必填）→ 什么都不补
- 默认标签不在本版的 `tag` 事实里 → 不补，记 `loot_map_destination_default_unresolved`，
  因为不知道它指向哪个结构
"""

from __future__ import annotations

import re
from pathlib import Path

from ...facts import Fact, FactStore
from ..loot import resolve_destination, structure_tags

__all__ = ["apply_default_destination", "exploration_map_default"]

# `DEFAULT_FEATURE = ConfiguredStructureTags.ON_TREASURE_MAPS`
DEFAULT_DESTINATION = re.compile(
    r"DEFAULT_FEATURE\s*=\s*ConfiguredStructureTags\.([A-Z][A-Z0-9_]*)"
)


def exploration_map_default(java_root: Path) -> str | None:
    """取本版 `exploration_map` 的默认目的地标签（不带 `#`）。找不到返回 None。

    按类名找文件，不靠索引：索引只收带获取语义锚点的候选，而这个类只是 loot 函数，
    一个锚点也不沾。类改名时什么都找不到，计数会露出来，不会默默跳过。

    常量名直接小写就是标签名（`ON_TREASURE_MAPS` → `minecraft:on_treasure_maps`）。
    名字对不上时由调用方用 `tag` 事实核对，不在这里猜。
    """
    for path in sorted(java_root.rglob("*ExplorationMap*.java")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = DEFAULT_DESTINATION.search(text)
        if match is not None:
            return f"minecraft:{match.group(1).lower()}"
    return None


def apply_default_destination(store: FactStore, tag: str) -> tuple[int, int]:
    """把没有 `destination` 的地图条目按默认标签补齐。

    返回 `(补上的条目数, 标签解析不出结构的条目数)`。后者不为零说明标签不在 tag 事实里，
    跳过而不是写一个空目的地——空列表在事实里的含义是「标签里没有结构」，不是「没查到」。
    """
    tags = structure_tags(store)
    if tag not in tags:
        return 0, sum(
            1
            for fact in store.of_kind("loot_table")
            for pool in fact.payload.get("pools") or ()
            for entry in pool.get("entries") or ()
            if entry.get("product_id") and not entry.get("map_destination")
        )

    structures = resolve_destination(f"#{tag}", tags)
    filled = 0
    for fact in list(store.of_kind("loot_table")):
        payload = fact.payload
        changed = False
        for pool in payload.get("pools") or ():
            for entry in pool.get("entries") or ():
                if not isinstance(entry, dict):
                    continue
                if not entry.get("product_id") or entry.get("map_destination"):
                    continue
                entry["map_destination"] = f"#{tag}"
                entry["map_structures"] = list(structures)
                entry["map_destination_default"] = True
                filled += 1
                changed = True
        if not changed:
            continue
        store.drop(fact)
        store.add(Fact(kind=fact.kind, payload=payload, prov=fact.prov, status=fact.status))
    return filled, 0
