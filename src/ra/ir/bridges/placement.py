"""放置桥接：item ↔ block 的方向由 `places` 事实给定。

这一层不重复造映射——`places` 事实已经由代码适配器给出，桥接只把它翻成规则。
"""

from __future__ import annotations

from ..nodes import Rule, node

__all__ = ["place_rules"]


def place_rules(block_ids: set[str], item_ids: set[str]) -> tuple[list[Rule], int]:
    """`block:X ← item:X`：有方块物品就能把方块摆出来。

    这条关系不需要逐个体取证——它由「方块物品」这个类决定。但 `code_link` 的
    `place_source` 是从 `Items.java` 的 `new BlockItem(...)` 逐个采的，批量注册
    （`ColorCollection`、`WeatheringCopperCollection`、`BlockItemIds` 派生）的方块
    一个都没有，于是这些方块的 `table ← block` 与 `item ← table` 全断。

    补这一层之后，`block ← item ← table ← block` 会成环，但那正是「合成 → 放置 →
    挖掉」的真实形状；只要物品有配方入口就通，没有入口的仍归因成环。

    返回 `(规则, 交叉校验失败的 id 数)`。
    """
    rules: list[Rule] = []
    mismatched = 0
    for ident in sorted(block_ids & item_ids):
        rules.append(
            Rule(
                id=f"bridge:place:{ident}",
                head=node("block", ident),
                body=(node("item", ident),),
                kind="places",
                family="bridge/place",
                meta={"basis": "方块物品可放置"},
            )
        )
    # 有方块没物品（如 `minecraft:wall_torch`）属正常，物品侧另有路径（`wallVariant`）
    mismatched = len(block_ids - item_ids)
    return rules, mismatched
