"""挖掘机制（`mining` 事实）的集成测试。

两条硬断言：

1. **方块集合必须等于注册表全集**。硬度是从 `Blocks.java` 的注册形态推出来的，
   漏一种形态（复制包装、颜色集合、构造器改写）都会少方块，而数值仍然看着正常。
2. **工具与材料表非空且关键值可对照**。工具速度是「哪条规则先命中」的顺序语义，
   只对数量不对内容，顺序错了也发现不了。

数值只取源码里写死的常量，跨版本比的是结构（标签名、规则顺序），不是具体版本号。
"""

from __future__ import annotations

import unittest

from tests.support import pack, store, why

COLORS = (
    "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
    "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black",
)


class _MiningBase:
    label = ""
    expected_tools = 0
    expected_materials = 0

    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = store(cls.label).of_kind("mining")

    def of_kind(self, kind: str) -> list[dict]:
        return [fact.payload for fact in self.facts if fact.payload["form"] == kind]

    def registry(self, name: str) -> set[str]:
        for fact in store(self.label).of_kind("registry"):
            if fact.payload["registry"] == name:
                return set(fact.payload["entries"])
        return set()

    def blocks(self) -> dict[str, dict]:
        return {payload["block"]: payload for payload in self.of_kind("block")}

    def tools(self) -> dict[str, dict]:
        return {payload["item"]: payload for payload in self.of_kind("tool")}

    def test_block_set_equals_registry(self) -> None:
        registered = self.registry("minecraft:block")
        self.assertTrue(registered)
        self.assertEqual(set(self.blocks()), registered)

    def test_tool_items_are_registered(self) -> None:
        items = self.registry("minecraft:item")
        self.assertTrue(items)
        self.assertTrue(set(self.tools()) <= items)

    def test_tool_and_material_counts(self) -> None:
        self.assertEqual(len(self.tools()), self.expected_tools)
        self.assertEqual(len(self.of_kind("material")), self.expected_materials)

    def test_every_tool_has_a_default_speed(self) -> None:
        for item, payload in self.tools().items():
            self.assertIsNotNone(payload["default_speed"], item)
            self.assertIsInstance(payload["rules"], list)

    def test_formula_captures_divisors(self) -> None:
        formulas = self.of_kind("formula")
        self.assertEqual(len(formulas), 1)
        payload = formulas[0]
        self.assertEqual(payload["unbreakable_hardness"], -1.0)
        self.assertEqual(payload["divisors"], {"correct_tool": 30, "wrong_tool": 100})
        self.assertEqual(payload["default_hardness"], 0.0)

    def test_requires_correct_tool_survives_copy(self) -> None:
        """复制语义要带上 `requiresCorrectToolForDrops`，否则工具要求会整批丢失。"""
        blocks = self.blocks()
        self.assertFalse(blocks["minecraft:stone"]["requires_correct_tool"] is None)
        self.assertTrue(blocks["minecraft:obsidian"]["requires_correct_tool"])


@unittest.skipUnless(pack("26.3"), why("26.3"))
class Mining263Test(_MiningBase, unittest.TestCase):
    label = "26.3"
    expected_tools = 38
    expected_materials = 7

    def test_infested_hardness_comes_from_constructor(self) -> None:
        """侵染方块在构造器里改写 `Properties`：宿主硬度的一半。"""
        blocks = self.blocks()
        self.assertEqual(blocks["minecraft:infested_stone"]["hardness"], 0.75)
        self.assertEqual(blocks["minecraft:infested_deepslate"]["hardness"], 1.5)

    def test_color_collections_expand_to_sixteen(self) -> None:
        blocks = self.blocks()
        for color in COLORS:
            self.assertIn(f"minecraft:{color}_wool", blocks)
            self.assertIn(f"minecraft:{color}_concrete", blocks)
        self.assertAlmostEqual(blocks["minecraft:white_wool"]["hardness"], 0.8)
        self.assertAlmostEqual(blocks["minecraft:white_concrete"]["hardness"], 1.8)

    def test_copper_collection_keeps_all_eight_states(self) -> None:
        blocks = self.blocks()
        for name in (
            "copper_bars",
            "exposed_copper_bars",
            "weathered_copper_bars",
            "oxidized_copper_bars",
            "waxed_copper_bars",
            "waxed_exposed_copper_bars",
            "waxed_weathered_copper_bars",
            "waxed_oxidized_copper_bars",
        ):
            self.assertIn(f"minecraft:{name}", blocks)

    def test_stair_inherits_base_hardness(self) -> None:
        blocks = self.blocks()
        self.assertEqual(
            blocks["minecraft:oak_stairs"]["hardness"], blocks["minecraft:oak_planks"]["hardness"]
        )

    def test_material_tool_rule_is_mineable_tag(self) -> None:
        tool = self.tools()["minecraft:diamond_pickaxe"]
        self.assertEqual(tool["tool_class"], "pickaxe")
        self.assertEqual(tool["material"], "diamond")
        rules = tool["rules"]
        self.assertEqual(rules[0]["selector"], "tag:minecraft:incorrect_for_diamond_tool")
        self.assertFalse(rules[0]["correct_for_drops"])
        self.assertEqual(rules[1]["selector"], "tag:minecraft:mineable/pickaxe")
        self.assertEqual(rules[1]["speed"], 8.0)

    def test_sword_rules_keep_declaration_order(self) -> None:
        tool = self.tools()["minecraft:iron_sword"]
        selectors = [rule["selector"] for rule in tool["rules"]]
        self.assertEqual(
            selectors,
            [
                "block:minecraft:cobweb",
                "tag:minecraft:sword_instantly_mines",
                "tag:minecraft:sword_efficient",
            ],
        )
        self.assertEqual(tool["rules"][0]["speed"], 15.0)
        self.assertEqual(tool["rules"][2]["speed"], 1.5)

    def test_shears_rules(self) -> None:
        rules = self.tools()["minecraft:shears"]["rules"]
        self.assertEqual(
            [(rule["selector"], rule["speed"]) for rule in rules],
            [
                ("block:minecraft:cobweb", 15.0),
                ("tag:minecraft:shears_extreme_breaking_speed", 15.0),
                ("tag:minecraft:shears_major_breaking_speed", 5.0),
                ("tag:minecraft:shears_minor_breaking_speed", 2.0),
            ],
        )

    def test_mace_and_trident_have_no_extra_rules(self) -> None:
        for item in ("minecraft:mace", "minecraft:trident"):
            self.assertEqual(self.tools()[item]["rules"], [])
            self.assertEqual(self.tools()[item]["default_speed"], 1.0)


@unittest.skipUnless(pack("1.18.2"), why("1.18.2"))
class Mining1182Test(_MiningBase, unittest.TestCase):
    label = "1.18.2"
    expected_tools = 32
    expected_materials = 6

    def test_digger_tool_uses_tier_speed(self) -> None:
        tool = self.tools()["minecraft:netherite_pickaxe"]
        self.assertEqual(tool["material"], "netherite")
        self.assertEqual(tool["tier_level"], 4)
        self.assertEqual(tool["rules"][0]["selector"], "tag:minecraft:mineable/pickaxe")
        self.assertEqual(tool["rules"][0]["speed"], 9.0)

    def test_drop_level_gates(self) -> None:
        gates = self.tools()["minecraft:iron_pickaxe"]["drop_level_gates"]
        self.assertEqual(
            [(gate["selector"], gate["min_level"]) for gate in gates],
            [
                ("tag:minecraft:needs_diamond_tool", 3),
                ("tag:minecraft:needs_iron_tool", 2),
                ("tag:minecraft:needs_stone_tool", 1),
            ],
        )

    def test_sword_and_shears_override_speed(self) -> None:
        sword = self.tools()["minecraft:diamond_sword"]
        self.assertEqual((sword["rules"][0]["selector"], sword["rules"][0]["speed"]),
                         ("block:minecraft:cobweb", 15.0))
        shears = self.tools()["minecraft:shears"]
        self.assertEqual(
            [(rule["selector"], rule["speed"]) for rule in shears["rules"]],
            [
                ("block:minecraft:cobweb", 15.0),
                ("tag:minecraft:leaves", 15.0),
                ("tag:minecraft:wool", 5.0),
                ("block:minecraft:vine", 2.0),
                ("block:minecraft:glow_lichen", 2.0),
            ],
        )

    def test_helper_registered_blocks_inherit_hardness(self) -> None:
        """`Blocks.log(...)` / `Blocks.leaves(...)` 把 Properties 藏在方法体里。"""
        blocks = self.blocks()
        self.assertEqual(blocks["minecraft:oak_log"]["hardness"], 2.0)
        self.assertEqual(blocks["minecraft:oak_leaves"]["hardness"], 0.2)
        self.assertEqual(blocks["minecraft:white_bed"]["hardness"], 0.2)
        self.assertEqual(blocks["minecraft:white_stained_glass"]["hardness"], 0.3)


if __name__ == "__main__":
    unittest.main()
