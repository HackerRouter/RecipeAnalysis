"""物品放置成方块（`Items.registerBlock` / `registerItem`）。

这是判断**哪些物品是方块物品**的唯一权威来源：jar 的 `blocks.json` 只有方块状态，
默认组件里也没有 `minecraft:block` 组件。

两个易错点由测试钉住：

1. 物品名**不能**靠字段名小写推。26.x 的 `BlockItemId.create("redstone_wire", "redstone")`
   双参数形式直接给出方块名与物品名；旧版只能推，推错由对账剔除
2. 26.3 的 `TORCH` 注册时 lambda 里还引用了 `WALL_TORCH`，取「第一个 `Blocks.X`」
   才是放置目标
"""

from __future__ import annotations

import unittest

from ra.adapters.source.identifiers import Names, block_item_names
from ra.adapters.source.idioms.place import PlaceSource, _call_args, _first_block_arg


from tests.support import pack, why

class ArgsTest(unittest.TestCase):
    def test_first_block_wins_over_lambda_reference(self) -> None:
        text = (
            "Items.registerBlock(BlockItemIds.TORCH, Blocks.TORCH, "
            "(Block b, Item.Properties p) -> new StandingAndWallBlockItem((Block)b, Blocks.WALL_TORCH, p))"
        )
        open_index = text.index("Items.registerBlock") + len("Items.registerBlock")
        self.assertEqual(_first_block_arg(text, open_index), "TORCH")

    def test_block_item_constructor(self) -> None:
        text = "Items.registerBlock(new BlockItem(Blocks.ANCIENT_DEBRIS, p))"
        open_index = text.index("Items.registerBlock") + len("Items.registerBlock")
        self.assertEqual(_first_block_arg(text, open_index), "ANCIENT_DEBRIS")

    def test_call_args_stops_at_matching_paren(self) -> None:
        text = "f(a, g(b), c) rest"
        args = _call_args(text, text.index("("))
        self.assertTrue(args.startswith("(a, g(b), c)"))
        self.assertNotIn("rest", args)


class NamesTest(unittest.TestCase):
    def test_both_names_from_constant(self) -> None:
        constants = {"block_item:REDSTONE_DUST": Names("redstone_wire", "redstone", False)}
        block, item, inferred = block_item_names(constants, "REDSTONE_DUST", "REDSTONE")
        self.assertEqual((block, item, inferred), ("redstone_wire", "redstone", False))

    def test_falls_back_to_field_name(self) -> None:
        block, item, inferred = block_item_names({}, "MISSING", "CUT_STANDSTONE_SLAB")
        self.assertEqual((block, item), ("cut_standstone_slab", "cut_standstone_slab"))
        self.assertTrue(inferred, "查不到常量时必须标记为推断，交给对账")


def _pack(label: str):
    return pack(label)


def _ingest(label: str, pack):
    from tests.support import store

    return store(label)


class PlaceIntegrationBase:
    label = ""
    min_expected = 0

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label, _pack(cls.label))

    def places(self) -> list:
        return [
            f for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == "place_source"
        ]

    def test_produces_most_block_items(self) -> None:
        self.assertGreater(len(self.places()), self.min_expected)

    def test_every_node_is_registered(self) -> None:
        """两端都必须在注册表里；这不是抽查，是全覆盖。"""
        items: set[str] = set()
        blocks: set[str] = set()
        for fact in self.store.of_kind("registry"):
            if fact.payload["registry"] == "minecraft:item":
                items = set(fact.payload["entries"])
            elif fact.payload["registry"] == "minecraft:block":
                blocks = set(fact.payload["entries"])
        self.assertTrue(items and blocks)
        for fact in self.places():
            link = fact.payload["link"]
            self.assertIn(link["head"].split(":", 1)[1], blocks)
            self.assertIn(fact.payload["meta"]["item"].split(":", 1)[1], items)

    def test_no_extra_inputs(self) -> None:
        """放置不投入额外物品；被放的那件本身由 head 表达。"""
        for fact in self.places():
            link = fact.payload["link"]
            self.assertEqual(link["inputs"], [])
            self.assertEqual(link["via"], [])


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class Place263Test(PlaceIntegrationBase, unittest.TestCase):
    label = "26.3"
    min_expected = 700

    def test_double_arg_constants_resolve(self) -> None:
        """26.x 的双参数常量给出物品名与方块名，不该再靠推断。"""
        by_item = {
            f.payload["meta"]["item"]: f.payload["link"]["head"] for f in self.places()
        }
        self.assertEqual(by_item.get("item:minecraft:redstone"), "block:minecraft:redstone_wire")
        self.assertEqual(by_item.get("item:minecraft:carrot"), "block:minecraft:carrots")
        for fact in self.places():
            self.assertFalse(
                fact.payload["meta"]["item_name_inferred"],
                f"26.x 有常量表，不该有推断：{fact.payload['meta']['item']}",
            )


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class Place1182Test(PlaceIntegrationBase, unittest.TestCase):
    label = "1.18.2"
    min_expected = 700

    def test_bad_names_are_dropped_and_logged(self) -> None:
        """1.18.2 没有常量表，物品名只能靠字段名推断，必然有推错的。

        实测 `CUT_STANDSTONE_SLAB`（Mojang 的拼写错误）→ 推断出 `cut_standstone_slab`，
        注册名其实是 `cut_sandstone_slab`。这种条必须被剔除并留痕，
        不能静默留在事实里让下游拿到不存在的节点。
        """
        skips = [
            row for row in self.store.ledger.rows
            if row.rule == "节点名由字段名推断，与注册表不符"
        ]
        self.assertTrue(skips, "没有对账记录，说明推断错误被漏掉了")
        self.assertTrue(any("cut_standstone_slab" in (row.note or "") for row in skips))


if __name__ == "__main__":
    unittest.main()
