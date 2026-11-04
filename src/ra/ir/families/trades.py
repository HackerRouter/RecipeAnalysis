"""交易族：`item:货物 ← yield ← 村民交易 + 付款物品`。

`trade` 事实归到 `trades` 族、链接种类 `yield`：产出者 + 条件 → 物品。
交易要三件事同时成立——有村民、有付款物、交易可发生：

```
item:minecraft:iron_boots  ←yield←  assume:villager_trade
                                    item:minecraft:emerald
```

## 为什么村民是一个假设节点

`assume:villager_trade` 表示「村民交易这件事可发生」。它由假设清单播种为真，
和 `assume:structure_loot` 同类：世界无限、村庄必然存在，但「村庄在哪」不是
本项目的推理对象（存在性语义）。

**流浪商人单列一条假设**（`assume:wandering_trader`）。它与职业村民的获取前提
不是同一件事：职业村民需要村庄与工作站、且会补货，流浪商人随机生成、不补货、
不依赖村庄。共用一个假设节点会让「去掉村庄还能不能拿到」这类问题无法单独问
（[ADR 0006](../../../../docs/adr/0006-trades.md)）。

职业与等级不进 `body`：它们不构成新的获取前提，只说明交易从哪来，
放 `meta` 供报告展示。

## 付款物缺失不静默丢

`wants` / `additional_wants` 的 id 如果不是物品（标签、按组件指定的物品等），
整条交易记进 `unresolved`，不产出一条 body 里挂着不存在节点的规则。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ...facts import Fact
from ..nodes import Rule, node

FAMILY = "trades"
# 职业村民：村庄存在、会补货
ASSUMED = "assume:villager_trade"
# 流浪商人：随机生成、不补货、不依赖村庄。前提不同，不能共用节点。
WANDERING_PROFESSION = "wandering_trader"
ASSUMED_WANDERING = "assume:wandering_trader"


def _assumption(profession: object) -> str:
    """按职业选前提节点。只有流浪商人有独立前提，其余职业共用村民交易。"""
    if profession == WANDERING_PROFESSION:
        return ASSUMED_WANDERING
    return ASSUMED


@dataclass
class TradesCompileResult:
    rules: list[Rule] = field(default_factory=list)
    # 付款物或货物不在物品注册表里
    unresolved: Counter = field(default_factory=Counter)
    # 按职业统计，供报告核对覆盖面
    by_profession: Counter = field(default_factory=Counter)
    # `layer=set` 的交易集合定义：不产规则，单独计数
    sets: int = 0


def _item_id(raw: object) -> str | None:
    """交易事实里的物品引用可能是字符串，也可能是 `{id, count}`。"""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        ident = raw.get("id")
        return ident if isinstance(ident, str) else None
    return None


def _item_list(raw: object) -> list[str | None]:
    """`wants` 在事实里可能是单个 `{id, count}`，也可能是列表。

    直接 `for item in raw` 会把 dict 的键当成条目（`wants` 是 `{"count":4,"id":...}`
    时迭代出来是 `"count"`、`"id"`），于是整族交易被判成付款物不是物品、
    一条规则也编不出来。所以先判形状再取。
    """
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        return [_item_id(raw)]
    if isinstance(raw, list):
        return [_item_id(item) for item in raw]
    return [None]


def compile_trades(facts: list[Fact], item_ids: set[str]) -> TradesCompileResult:
    """把交易事实编译成 `yield` 规则。"""
    result = TradesCompileResult()

    for fact in facts:
        payload = fact.payload
        layer = payload.get("layer")

        # `layer == "set"` 是「一级交易集合」的定义（`trades_ref: #minecraft:armorer/level_1`），
        # 里面没有货物，只有对交易标签的引用。它不产出规则，但不是解析缺陷，
        # 与「货物取不到」分开计数。
        if layer == "set":
            result.sets += 1
            continue

        gives = _item_id(payload.get("gives"))
        wants = _item_list(payload.get("wants"))
        extra = _item_list(payload.get("additional_wants"))
        costs = [ident for ident in wants + extra if ident]

        if not gives or gives not in item_ids:
            result.unresolved[f"gives:{gives}"] += 1
            continue
        if any(not ident for ident in wants + extra):
            result.unresolved["wants:form"] += 1
            continue
        missing = [c for c in costs if c not in item_ids]
        if missing:
            result.unresolved[f"wants:{missing[0]}"] += 1
            continue

        result.by_profession[str(payload.get("profession") or "?")] += 1
        assumed = _assumption(payload.get("profession"))
        result.rules.append(
            Rule(
                id=f"trade:{fact.prov.file}",
                head=node("item", gives),
                body=(assumed, *[node("item", c) for c in costs]),
                kind="yield",
                family=FAMILY,
                meta={
                    "trade": payload.get("trade"),
                    "profession": payload.get("profession"),
                    "level": payload.get("level"),
                    "layer": payload.get("layer"),
                    "gives_count": (payload.get("gives") or {}).get("count")
                    if isinstance(payload.get("gives"), dict)
                    else None,
                },
                prov=fact.prov,
            )
        )

    return result
