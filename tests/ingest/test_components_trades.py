"""默认组件与交易的语法归一。

两条重点：
1. `!` 前缀是「不具有」，绝不能读成「具有且为空」——否则变体维度推导会多出假维度。
2. 交易组带 `random_sequence`，形状判定必须先于战利品表，否则整族交易会被当成战利品表。
"""

from __future__ import annotations

import unittest

from oa.adapters.components import split_components
from oa.adapters.trades import parse_item_stack
from oa.probe.shapes import (
    LOOT_TABLE,
    TAG,
    TRADE_OFFER,
    TRADE_SET,
    classify,
)


class NegationTest(unittest.TestCase):
    def test_bang_prefix_goes_to_absent(self) -> None:
        present, absent, problems = split_components(
            {"minecraft:food": {"nutrition": 4}, "!minecraft:damage": {}}
        )
        self.assertEqual(present, {"minecraft:food": {"nutrition": 4}})
        self.assertEqual(absent, ["minecraft:damage"])
        self.assertEqual(problems, [])
        # 关键：`!minecraft:damage` 的值（空对象）不得出现在 present
        self.assertNotIn("minecraft:damage", present)

    def test_bang_with_non_empty_value_still_means_absent(self) -> None:
        # 即使带 `!` 的键给了非空值，语义仍是「不具有」
        present, absent, _ = split_components({"!minecraft:tool": {"rules": []}})
        self.assertEqual(present, {})
        self.assertEqual(absent, ["minecraft:tool"])

    def test_no_marker_means_absent_by_omission(self) -> None:
        # 26.3 实测：键缺席即不具有，absent 为空
        present, absent, problems = split_components({"minecraft:max_stack_size": 64})
        self.assertEqual(present, {"minecraft:max_stack_size": 64})
        self.assertEqual(absent, [])
        self.assertEqual(problems, [])

    def test_conflicting_marker_is_reported(self) -> None:
        _, absent, problems = split_components(
            {"minecraft:food": {}, "!minecraft:food": {}}
        )
        self.assertEqual(absent, ["minecraft:food"])
        self.assertTrue(any("同时出现" in p for p in problems))

    def test_bare_bang_is_reported(self) -> None:
        _, _, problems = split_components({"!": {}})
        self.assertTrue(any("没有组件名" in p for p in problems))

    def test_non_object_is_reported(self) -> None:
        _, _, problems = split_components([1, 2])
        self.assertTrue(problems)

    def test_empty_document(self) -> None:
        _, _, problems = split_components(None)
        self.assertTrue(any("缺少" in p for p in problems))


class TradeShapeTest(unittest.TestCase):
    def test_offer_shape(self) -> None:
        self.assertEqual(
            classify({"gives": {"id": "minecraft:a"}, "wants": {"id": "minecraft:b"}}),
            TRADE_OFFER,
        )

    def test_set_shape_wins_over_loot_table(self) -> None:
        # 交易组带 random_sequence，若不先判会被当成战利品表
        doc = {
            "amount": 2,
            "random_sequence": "minecraft:trade_set/armorer/level_1",
            "trades": "#minecraft:armorer/level_1",
        }
        self.assertEqual(classify(doc), TRADE_SET)

    def test_loot_table_still_recognised(self) -> None:
        self.assertEqual(classify({"pools": []}), LOOT_TABLE)
        # 可疑方块的空表：只有 type + random_sequence
        self.assertEqual(
            classify({"type": "minecraft:block", "random_sequence": "minecraft:x"}), LOOT_TABLE
        )

    def test_tag_still_wins(self) -> None:
        self.assertEqual(classify({"values": ["minecraft:a"]}), TAG)

    def test_amount_alone_is_not_a_trade_set(self) -> None:
        # 只有 amount 没有 trades 不算交易组
        self.assertNotEqual(classify({"amount": 2}), TRADE_SET)


class ItemStackTest(unittest.TestCase):
    def test_object_form(self) -> None:
        self.assertEqual(
            parse_item_stack({"id": "minecraft:emerald", "count": 4}),
            {"id": "minecraft:emerald", "count": 4},
        )

    def test_bare_string(self) -> None:
        self.assertEqual(parse_item_stack("minecraft:emerald"), {"id": "minecraft:emerald", "count": 1})

    def test_components_preserved(self) -> None:
        parsed = parse_item_stack(
            {"id": "minecraft:potion", "count": 1, "components": {"minecraft:potion_contents": {}}}
        )
        self.assertIn("components", parsed)

    def test_unparsable(self) -> None:
        self.assertIsNone(parse_item_stack({"no_id": 1}))
        self.assertIsNone(parse_item_stack(42))


if __name__ == "__main__":
    unittest.main()
