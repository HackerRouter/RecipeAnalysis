"""反编译源码侧提取的单元测试。

用真实的反编译源码片段（已脱敏、只保留结构）验证解析器，不依赖输入包。
集成测试另有一组，跑真实输入包。
"""

from __future__ import annotations

import unittest

from ra.adapters.source.index import ANCHORS, build_index
from ra.adapters.source.javatext import (
    find_constructor_calls,
    find_method_body,
    java_ident,
    split_args,
    strip_comments,
)
from ra.adapters.source.lootconstants import LootConstants

BUILTIN_263 = """
package net.minecraft.world.level.storage.loot;

public class BuiltInLootTables {
    public static final ResourceKey<LootTable> SHEAR_SHEEP = BuiltInLootTables.register("shearing/sheep");
    public static final ColorCollection<ResourceKey<LootTable>> SHEAR_DYED_SHEEP = ColorCollection.NAMES.map(color -> BuiltInLootTables.register("shearing/sheep/" + color));
    public static final ResourceKey<LootTable> CHICKEN_LAY = BuiltInLootTables.register("gameplay/chicken_lay");
}
"""

BUILTIN_1182 = """
public class BuiltInLootTables {
    public static final ResourceLocation EMPTY = new ResourceLocation("empty");
    public static final ResourceLocation SPAWN_BONUS_CHEST = BuiltInLootTables.register("chests/spawn_bonus_chest");
}
"""

COLOR_COLLECTION_DEF = """
public final class ColorCollection<T> {
    public static final ColorCollection<DyeColor> VALUES = new ColorCollection<DyeColor>(DyeColor.WHITE, DyeColor.ORANGE, DyeColor.MAGENTA);
    public static final ColorCollection<String> NAMES = VALUES.map(DyeColor::getName);
}
"""


class LootConstantTest(unittest.TestCase):
    def test_single_constant_263(self) -> None:
        from ra.adapters.source import lootconstants

        constants = lootconstants._parse_colors_from_text(COLOR_COLLECTION_DEF)
        self.assertEqual(constants, ["white", "orange", "magenta"])

        text = strip_comments(BUILTIN_263)
        single = dict(lootconstants.SINGLE.findall(text))
        self.assertEqual(single["SHEAR_SHEEP"], "shearing/sheep")

    def test_color_collection_expands(self) -> None:
        from ra.adapters.source import lootconstants

        text = strip_comments(BUILTIN_263)
        found = lootconstants.COLOR_COLLECTION.findall(text)
        self.assertEqual(len(found), 1)
        name, prefix = found[0]
        self.assertEqual(name, "SHEAR_DYED_SHEEP")
        self.assertEqual(prefix, "shearing/sheep/")

    def test_legacy_type_is_resource_location(self) -> None:
        from ra.adapters.source import lootconstants

        text = strip_comments(BUILTIN_1182)
        single = dict(lootconstants.SINGLE.findall(text))
        self.assertEqual(single["SPAWN_BONUS_CHEST"], "chests/spawn_bonus_chest")

    def test_expand_single_returns_one(self) -> None:
        constants = LootConstants(
            single={"SHEAR_SHEEP": "shearing/sheep"},
            collections={"SHEAR_DYED_SHEEP": ["shearing/sheep/white"]},
            colors=["white"],
        )
        self.assertEqual(constants.expand("SHEAR_SHEEP"), ["minecraft:shearing/sheep"])
        self.assertEqual(constants.expand("SHEAR_DYED_SHEEP"), ["minecraft:shearing/sheep/white"])
        self.assertEqual(constants.expand("UNKNOWN"), [])


class JavaTextTest(unittest.TestCase):
    def test_strip_comments_keeps_strings(self) -> None:
        text = 'a(); // note "x"\n/* block "y" */ b("keep // this");'
        out = strip_comments(text)
        self.assertNotIn("note", out)
        self.assertIn("keep // this", out)

    def test_find_method_body(self) -> None:
        text = "public void shear(SoundSource s) {\n  a();\n  b();\n}\n"
        body = find_method_body(text, r"public\s+void\s+shear\s*\(")
        self.assertIsNotNone(body)
        self.assertIn("a();", body)

    def test_split_args_handles_nesting(self) -> None:
        self.assertEqual(
            split_args('Items.WHEAT, 20, new ItemStack(Items.A, 2), "a,b"'),
            ["Items.WHEAT", "20", "new ItemStack(Items.A, 2)", '"a,b"'],
        )

    def test_find_constructor_calls(self) -> None:
        text = "x = new EmeraldForItems(Items.WHEAT, 20, 16, 2);"
        calls = find_constructor_calls(text, "EmeraldForItems")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[0], "Items.WHEAT")
        self.assertEqual(len(calls[0].args), 4)

    def test_java_ident(self) -> None:
        self.assertEqual(java_ident("Items.WHEAT"), "wheat")
        self.assertEqual(java_ident("Blocks.OAK_PLANKS"), "oak_planks")
        self.assertIsNone(java_ident("someLocal"))


class AnchorPrecisionTest(unittest.TestCase):
    """锚点必须精确到调用形态。裸类名命中会把 import 也当成获取关系。"""

    def test_type_reference_is_not_an_anchor(self) -> None:
        import re

        import_only = "import net.minecraft.world.level.storage.loot.LootTable;\n"
        for name, (pattern, _) in ANCHORS.items():
            self.assertIsNone(
                re.search(pattern, import_only), f"锚点 {name} 误命中 import 语句"
            )

    def test_real_call_is_detected(self) -> None:
        import re

        call = "this.dropFromShearingLootTable(level, BuiltInLootTables.SHEAR_SHEEP, tool, cb);"
        self.assertIsNotNone(re.search(ANCHORS["loot_table_call"][0], call))
        self.assertIsNotNone(re.search(ANCHORS["loot_table_key"][0], call))


class TradeDirectionTest(unittest.TestCase):
    """交易方向必须从 MerchantOffer 参数顺序推出，不能靠类名。

    实测踩过的坑：`EmeraldForItems(Items.WHEAT, 20, 16, 2)` 是「20 小麦换 1 绿宝石」，
    名字读起来像反的。若按名字猜，会把整个交易表的方向搞反。
    """

    def test_emerald_for_items_gives_emerald(self) -> None:
        from ra.adapters.source.idioms.trades import OFFER_SHAPES

        shape = OFFER_SHAPES["EmeraldForItems"]
        args = ["Items.WHEAT", "20", "16", "2"]
        self.assertEqual(shape.resolve_give(args), ("emerald", 1))
        self.assertEqual(shape.resolve_pay(args), ("wheat", 20))

    def test_items_for_emeralds_gives_item(self) -> None:
        from ra.adapters.source.idioms.trades import OFFER_SHAPES

        shape = OFFER_SHAPES["ItemsForEmeralds"]
        args = ["Items.BREAD", "1", "6", "16", "1"]
        self.assertEqual(shape.resolve_give(args), ("bread", 6))
        self.assertEqual(shape.resolve_pay(args), ("emerald", 1))

    def test_link_head_is_given_item(self) -> None:
        from ra.adapters.source.idioms.trades import offers_to_link

        link = offers_to_link(("EmeraldForItems", ["Items.WHEAT", "20", "16", "2"]), "farmer", 1)
        self.assertEqual(link.head, "item:minecraft:emerald")
        self.assertIn("item:minecraft:wheat", link.inputs)
        self.assertEqual(link.meta["pay_counts"], [20])

    def test_multi_payment_shape(self) -> None:
        """要两样东西的交易：两样都进 inputs。

        `EnchantBookForEmeralds` 的 getOffer 是
        `MerchantOffer(emeralds, BOOK, enchantedBook, ...)`，两个支付位。
        只取第一个会得到「绿宝石换附魔书」，把书这个前提抹掉。
        """
        from ra.adapters.source.idioms.trades import offers_to_link

        link = offers_to_link(("EnchantBookForEmeralds", ["1"]), "librarian", 1)
        self.assertEqual(link.head, "item:minecraft:enchanted_book")
        items = {n for n in link.inputs if n.startswith("item:")}
        self.assertEqual(items, {"item:minecraft:emerald", "item:minecraft:book"})
        self.assertIn("assume:villager_trade", link.inputs)
        self.assertIn("give_variant", link.meta)

    def test_map_payment_expands_to_several_links(self) -> None:
        """支付物取决于村民类型时，按 map 的 value 展开成多条。

        `EmeraldsForVillagerTypeItem(1, 12, 30, ImmutableMap…put(PLAINS, OAK_BOAT)…)`
        是「每种村民用地的一种船换绿宝石」。只取第一个会漏掉其余类型。
        """
        from ra.adapters.source.idioms.trades import offers_to_links

        args = [
            "1",
            "12",
            "30",
            'ImmutableMap.builder().put(VillagerType.PLAINS, Items.OAK_BOAT)'
            '.put(VillagerType.DESERT, Items.JUNGLE_BOAT).build()',
        ]
        links = offers_to_links(("EmeraldsForVillagerTypeItem", args), "farmer", 1)
        self.assertEqual(len(links), 2)
        paid = {item for link in links for item in link.inputs if item.startswith("item:")}
        self.assertEqual(
            paid,
            {"item:minecraft:oak_boat", "item:minecraft:jungle_boat"},
        )
        self.assertTrue(all(link.head == "item:minecraft:emerald" for link in links))

    def test_overload_is_dispatched_by_argc(self) -> None:
        """`ItemsAndEmeraldsToItems` 的 6 参与 7 参重载实参位置不同。

        6 参把 emeraldCost 折叠成 1，于是 to/toCount 在 arg2/arg3；7 参显式给出
        emeraldCost，整体后移到 arg3/arg4。按 6 参读 7 参会取到绿宝石数量当物品名。
        """
        from ra.adapters.source.idioms.trades import offers_to_link

        six = offers_to_link(
            ("ItemsAndEmeraldsToItems", ["Items.COD", "6", "Items.COOKED_COD", "6", "16", "1"]),
            "fisherman",
            1,
        )
        self.assertEqual(six.head, "item:minecraft:cooked_cod")
        self.assertEqual(six.meta["give_count"], 6)

        seven = offers_to_link(
            (
                "ItemsAndEmeraldsToItems",
                ["Items.COD", "6", "2", "Items.COOKED_COD", "6", "16", "1"],
            ),
            "fisherman",
            1,
        )
        self.assertEqual(seven.head, "item:minecraft:cooked_cod")
        self.assertEqual(seven.meta["pay_counts"], [2, 6])

    def test_link_head_is_given_item_for_reverse_shape(self) -> None:
        from ra.adapters.source.idioms.trades import offers_to_link

        link = offers_to_link(("ItemsForEmeralds", ["Items.BREAD", "1", "6", "16", "1"]), "farmer", 1)
        self.assertEqual(link.head, "item:minecraft:bread")
        self.assertIn("item:minecraft:emerald", link.inputs)
        self.assertEqual(link.meta["give_count"], 6)

    def test_every_shape_has_basis(self) -> None:
        from ra.adapters.source.idioms.trades import OFFER_SHAPES

        for name, shape in OFFER_SHAPES.items():
            self.assertTrue(shape.basis, f"{name} 缺推导依据")
            self.assertIn("MerchantOffer", shape.basis, f"{name} 的依据没指向参数顺序")


if __name__ == "__main__":
    unittest.main()
