"""挖掘机制提取的单元测试（不读输入包）。

只钉判据，不钉版本数值：合成一段最小 Java 片段，验证
「`Properties` 链怎么读」「集合注册怎么展开」「工具规则怎么切」。
"""

from __future__ import annotations

import unittest

from ra.adapters.source.idioms import mining as m


class FloatTest(unittest.TestCase):
    def test_accepts_java_float_literals(self) -> None:
        for token, expected in (
            ("1.5f", 1.5),
            ("2.0F", 2.0),
            ("0.0f", 0.0),
            ("-1.0f", -1.0),
            ("3", 3.0),
            ("(float)0.5f", 0.5),
        ):
            self.assertEqual(m._as_float(token), expected, token)

    def test_rejects_expressions(self) -> None:
        self.assertIsNone(m._as_float("x / 2.0f"))
        self.assertIsNone(m._as_float("Float.MAX_VALUE"))


class ArithmeticTest(unittest.TestCase):
    def test_host_half(self) -> None:
        self.assertEqual(m._arithmetic("1.5 / 2.0f"), 0.75)

    def test_passes_through_literal(self) -> None:
        self.assertEqual(m._arithmetic("0.75f"), 0.75)

    def test_rejects_unknown(self) -> None:
        self.assertIsNone(m._arithmetic("host.destroyTime()"))


class PropsChainTest(unittest.TestCase):
    def test_strength_sets_both_fields(self) -> None:
        props = m._eval_props(
            "BlockBehaviour.Properties.of().strength(1.5f, 6.0f).requiresCorrectToolForDrops()",
            m._Ctx(),
        )
        self.assertEqual((props.hardness, props.explosion, props.requires_tool), (1.5, 6.0, True))

    def test_single_argument_strength_mirrors(self) -> None:
        props = m._eval_props("BlockBehaviour.Properties.of().strength(2.0f)", m._Ctx())
        self.assertEqual((props.hardness, props.explosion), (2.0, 2.0))

    def test_instabreak_is_zero(self) -> None:
        props = m._eval_props("BlockBehaviour.Properties.of().instabreak().sound(SoundType.GRASS)", m._Ctx())
        self.assertEqual((props.hardness, props.explosion), (0.0, 0.0))

    def test_missing_strength_defaults_to_zero(self) -> None:
        props = m._eval_props("BlockBehaviour.Properties.of().mapColor(MapColor.CLAY)", m._Ctx())
        self.assertEqual(props.hardness, 0.0)

    def test_copy_inherits_hardness(self) -> None:
        ctx = m._Ctx()
        ctx.blocks["STONE"] = m._Block("stone", m._Props(1.5, 6.0, True))
        props = m._eval_props(
            "BlockBehaviour.Properties.ofLegacyCopy(STONE).sound(SoundType.STONE)", ctx
        )
        self.assertEqual((props.hardness, props.explosion, props.requires_tool), (1.5, 6.0, True))

    def test_copy_then_override(self) -> None:
        ctx = m._Ctx()
        ctx.blocks["STONE"] = m._Block("stone", m._Props(1.5, 6.0, True))
        props = m._eval_props("BlockBehaviour.Properties.copy(STONE).strength(4.5f, 3.0f)", ctx)
        self.assertEqual((props.hardness, props.explosion), (4.5, 3.0))

    def test_helper_method_is_expanded(self) -> None:
        ctx = m._Ctx()
        ctx.helpers["buttonProperties"] = (
            (),
            "return BlockBehaviour.Properties.of().noCollision().strength(0.5f)"
            ".pushReaction(PushReaction.POPPED);",
        )
        props = m._eval_props("Blocks.buttonProperties()", ctx)
        self.assertEqual(props.hardness, 0.5)

    def test_helper_with_local_variable(self) -> None:
        ctx = m._Ctx()
        ctx.helpers["wallVariant"] = (
            ("standingBlock", "copyName"),
            "BlockBehaviour.Properties wallProperties = BlockBehaviour.Properties.of();"
            "return wallProperties;",
        )
        props = m._eval_props("Blocks.wallVariant(BANNER.pick(color), true)", ctx)
        self.assertEqual(props.hardness, 0.0)

    def test_unresolvable_copy_is_reported(self) -> None:
        props = m._eval_props("BlockBehaviour.Properties.ofLegacyCopy(UNKNOWN)", m._Ctx())
        self.assertIsNotNone(props.unresolved)

    def test_non_literal_strength_is_reported(self) -> None:
        props = m._eval_props(
            "BlockBehaviour.Properties.of().strength(host.defaultDestroyTime())", m._Ctx()
        )
        self.assertIsNotNone(props.unresolved)


class CollectionExpansionTest(unittest.TestCase):
    def test_color_collection_covers_sixteen(self) -> None:
        ctx = m._Ctx()
        ctx.ids["BlockItemIds"] = {
            "WOOL": m._Ids("color", tuple((color, f"{color}_wool") for color in (
                "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
                "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black",
            )))
        }
        notes: list[str] = []
        text = (
            "public static final ColorCollection<Block> WOOL = "
            "ColorCollection.registerBlocks(BlockItemIds.WOOL, Blocks::register, "
            "(dyeColor, p) -> new Block((BlockBehaviour.Properties)p), "
            "color -> BlockBehaviour.Properties.of().strength(0.8f).sound(SoundType.WOOL));"
        )
        blocks = m._scan_blocks(text, ctx, notes)
        self.assertEqual(notes, [])
        self.assertEqual(len(blocks), 16)
        self.assertEqual({block.block_id for block in blocks}, {f"{color}_wool" for color in (
            "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
            "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black",
        )})
        self.assertTrue(all(block.props.hardness == 0.8 for block in blocks))

    def test_copper_collection_keeps_eight_variants(self) -> None:
        ctx = m._Ctx()
        labels = (
            ("weathering", "copper_bars"),
            ("weathering", "exposed_copper_bars"),
            ("weathering", "weathered_copper_bars"),
            ("weathering", "oxidized_copper_bars"),
            ("waxed", "waxed_copper_bars"),
            ("waxed", "waxed_exposed_copper_bars"),
            ("waxed", "waxed_weathered_copper_bars"),
            ("waxed", "waxed_oxidized_copper_bars"),
        )
        ctx.ids["BlockItemIds"] = {"COPPER_BARS": m._Ids("copper", labels)}
        notes: list[str] = []
        text = (
            "public static final WeatheringCopperCollection<Block> COPPER_BARS = "
            "WeatheringCopperCollection.registerBlocks(BlockItemIds.COPPER_BARS, Blocks::register, "
            "(s, p) -> new IronBarsBlock((BlockBehaviour.Properties)p), "
            "(s, p) -> new WeatheringCopperBarsBlock((BlockBehaviour.Properties)p), "
            "state -> BlockBehaviour.Properties.of().strength(5.0f, 6.0f));"
        )
        blocks = m._scan_blocks(text, ctx, notes)
        self.assertEqual(notes, [])
        self.assertEqual({block.block_id for block in blocks}, {item[1] for item in labels})
        self.assertTrue(all(block.props.hardness == 5.0 for block in blocks))


class WrapperTest(unittest.TestCase):
    def test_stair_copies_base(self) -> None:
        ctx = m._Ctx()
        ctx.blocks["PLANKS"] = m._Block("oak_planks", m._Props(2.0, 3.0, False))
        ctx.ids["BlockItemIds"] = {"OAK_STAIRS": m._Ids("scalar", (("", "oak_stairs"),))}
        notes: list[str] = []
        blocks = m._scan_blocks(
            "public static final Block OAK_STAIRS = "
            "Blocks.registerStair(BlockItemIds.OAK_STAIRS, PLANKS);",
            ctx,
            notes,
        )
        self.assertEqual(notes, [])
        self.assertEqual([block.block_id for block in blocks], ["oak_stairs"])
        self.assertEqual(blocks[0].props.hardness, 2.0)

    def test_slab_override(self) -> None:
        ctx = m._Ctx()
        ctx.blocks["PLANKS"] = m._Block("oak_planks", m._Props(2.0, 3.0, False))
        ctx.ids["BlockItemIds"] = {"X": m._Ids("scalar", (("", "x_slab"),))}
        notes: list[str] = []
        blocks = m._scan_blocks(
            "public static final Block X = Blocks.registerSlab(BlockItemIds.X, PLANKS, 0.5f);",
            ctx,
            notes,
        )
        self.assertEqual(blocks[0].props.hardness, 0.5)

    def test_string_literal_id_for_legacy_version(self) -> None:
        ctx = m._Ctx()
        notes: list[str] = []
        blocks = m._scan_blocks(
            'public static final Block STONE = Blocks.register("stone", '
            "new Block(BlockBehaviour.Properties.of().strength(1.5f, 6.0f)));",
            ctx,
            notes,
        )
        self.assertEqual(notes, [])
        self.assertEqual(blocks[0].block_id, "stone")
        self.assertEqual(blocks[0].props.hardness, 1.5)


class ConditionalRulesTest(unittest.TestCase):
    def test_if_return_rules(self) -> None:
        ctx = m._Ctx()
        ctx.blocks["COBWEB"] = m._Block("cobweb", m._Props(4.0))
        ctx.tags["LEAVES"] = "leaves"
        body = (
            "if (blockState.is(Blocks.COBWEB)) { return 15.0f; }"
            "if (blockState.is(BlockTags.LEAVES) || material == Material.PLANT) { return 1.5f; }"
            "return 1.0f;"
        )
        notes: list[str] = []
        rules = m._if_return_rules(body, ctx, notes)
        self.assertEqual(notes, [])
        self.assertEqual(
            rules,
            [
                {"selector": "block:minecraft:cobweb", "speed": 15.0, "correct_for_drops": None},
                {"selector": "tag:minecraft:leaves", "speed": 1.5, "correct_for_drops": None},
                {"selector": "material:minecraft:plant", "speed": 1.5, "correct_for_drops": None},
            ],
        )


class ToolRuleTest(unittest.TestCase):
    def test_component_expression(self) -> None:
        props = (
            "new Item.Properties().durability(238)"
            ".component(DataComponents.TOOL, ShearsItem.createToolProperties())"
        )
        self.assertEqual(m._component_tool_expression(props), "ShearsItem.createToolProperties()")

    def test_rule_rules(self) -> None:
        ctx = m._Ctx()
        ctx.blocks["COBWEB"] = m._Block("cobweb", m._Props(4.0))
        ctx.tags["SWORD_EFFICIENT"] = "sword_efficient"
        expr = (
            "new Tool(List.of("
            "Tool.Rule.minesAndDrops(HolderSet.direct(Blocks.COBWEB.builtInRegistryHolder()), 15.0f), "
            "Tool.Rule.overrideSpeed(registrationLookup.getOrThrow(BlockTags.SWORD_EFFICIENT), 1.5f)"
            "), 1.0f, 2, false)"
        )
        notes: list[str] = []
        default, rules = m._parse_tool_rules(expr, ctx, notes)
        self.assertEqual(notes, [])
        self.assertEqual(default, 1.0)
        self.assertEqual(
            rules,
            [
                {"selector": "block:minecraft:cobweb", "speed": 15.0, "correct_for_drops": True},
                {"selector": "tag:minecraft:sword_efficient", "speed": 1.5, "correct_for_drops": None},
            ],
        )


if __name__ == "__main__":
    unittest.main()
