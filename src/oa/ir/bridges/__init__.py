"""桥接规则：把「常识」变成普通规则。

桥接层是 IR 的一部分，产出仍是普通规则。四类：

| 桥接 | 产物 | 依据 | 模块 |
|---|---|---|---|
| tag → OR | 每成员一条 `implies` | tag 事实，不写清单 | `vocabulary` |
| station | `station:X ← item:X` | 有该设备物品即可用 | `vocabulary` |
| 表的产出者 | `table:T ← block:B` | `holds` 事实优先，缺则目录映射 | `mechanics` |
| item ↔ block | 由 `places` 事实给 | code_link，不重复 | `placement` |

按知识表分文件，是为了让「改一条知识 → 改一个文件」在目录结构上可见：
机制类桥接各自独占一个函数、一个模块；词汇类桥接共享 `vocabulary`，
因为它们的共同点是「把名字翻成规则」而不是「读某张表」。
"""

from __future__ import annotations

from .base import BridgeResult
from .entities import entity_behaviour_rules, entity_source_rules
from .harvest import HarvestResult, derive_capabilities, harvest_rules
from .mechanics import convention_transform_rules, table_provider_rules
from .placement import place_rules
from .vocabulary import enchant_rules, station_rules, tag_rules, tool_rules

__all__ = [
    "BridgeResult",
    "HarvestResult",
    "convention_transform_rules",
    "derive_capabilities",
    "enchant_rules",
    "entity_behaviour_rules",
    "entity_source_rules",
    "harvest_rules",
    "place_rules",
    "station_rules",
    "table_provider_rules",
    "tag_rules",
    "tool_rules",
]
