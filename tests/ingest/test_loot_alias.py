"""方块借用他人战利品表（`dropsLike` / `wallVariant`）。

这是「挖掉 `wall_torch` 掉火把」这类路径的唯一来源：数据包里既没有 `wall_torch`
的表，也没有别名声明。

两个易错点由测试钉住：

1. 26.3 的写法是 `wallVariant(TORCH, true)`——**裸标识符**且带第二个布尔参数，
   不是 `wallVariant(Blocks.TORCH)`
2. `head` 里的表 id 是按方块名推的，必须对账；推错就是悬空边
"""

from __future__ import annotations

import unittest

from oa.adapters.source.idioms.loot_alias import ALIAS_CALL, REGISTER_DECL, LootAliases


from tests.support import pack, why

class AliasRegexTest(unittest.TestCase):
    def test_legacy_drops_like(self) -> None:
        text = (
            'public static final Block WALL_TORCH = Blocks.register("wall_torch", '
            "new WallTorchBlock(BlockBehaviour.Properties.of().dropsLike(Blocks.TORCH)));"
        )
        self.assertEqual(REGISTER_DECL.findall(text), ["WALL_TORCH"])
        self.assertEqual(ALIAS_CALL.findall(text), ["TORCH"])

    def test_modern_wall_variant_with_bool(self) -> None:
        """26.3：裸标识符 + 布尔参数。"""
        text = (
            "public static final Block WALL_TORCH = Blocks.register(BlockIds.WALL_TORCH, "
            "(BlockBehaviour.Properties p) -> new WallTorchBlock(p), "
            "Blocks.wallVariant(TORCH, true));"
        )
        self.assertEqual(REGISTER_DECL.findall(text), ["WALL_TORCH"])
        self.assertEqual(ALIAS_CALL.findall(text), ["TORCH"])

    def test_modern_with_block_ids_prefix(self) -> None:
        text = "Blocks.wallVariant(BlockIds.OAK_SIGN, false)"
        self.assertEqual(ALIAS_CALL.findall(text), ["OAK_SIGN"])

    def test_plain_register_has_no_alias(self) -> None:
        text = 'Block STONE = Blocks.register("stone", new Block(Properties.of()));'
        self.assertEqual(ALIAS_CALL.findall(text), [])


def _pack(label: str):
    return pack(label)


def _ingest(label: str, pack):
    from tests.support import store

    return store(label)


class AliasIntegrationBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label, _pack(cls.label))

    def aliases(self) -> list:
        return [
            f for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == "loot_alias"
        ]

    def test_alias_count(self) -> None:
        self.assertEqual(len(self.aliases()), self.expected)

    def test_head_points_at_borrowed_table(self) -> None:
        for fact in self.aliases():
            link = fact.payload["link"]
            self.assertEqual(link["kind"], "holds")
            self.assertTrue(link["head"].startswith("table:minecraft:blocks/"))
            self.assertEqual(len(link["via"]), 1)
            self.assertTrue(link["via"][0].startswith("block:minecraft:"))
            self.assertEqual(link["inputs"], [], "挖方块不需投入，inputs 必须为空")

    def test_owner_is_not_the_borrowed_block(self) -> None:
        """`wall_torch` 借 `torch` 的表；不能是同一个方块。"""
        for fact in self.aliases():
            link = fact.payload["link"]
            owner = link["via"][0].split(":", 1)[1]
            borrowed = link["head"].rsplit("/", 1)[-1]
            self.assertNotEqual(owner, f"minecraft:{borrowed}", f"{owner} 借了自己的表")

    def test_no_dangling_table_reference(self) -> None:
        """表 id 是推出来的，必须真实存在；不存在就是悬空边。"""
        known = {f.payload["table"] for f in self.store.of_kind("loot_table")}
        for fact in self.aliases():
            table_id = fact.payload["link"]["head"][len("table:") :]
            self.assertIn(table_id, known, f"引用了不存在的表：{table_id}")

    def test_nothing_failed(self) -> None:
        self.assertEqual(self.store.ledger.failed(), [])


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class Alias263Test(AliasIntegrationBase, unittest.TestCase):
    label = "26.3"
    expected = 47


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class Alias1182Test(AliasIntegrationBase, unittest.TestCase):
    label = "1.18.2"
    expected = 43


if __name__ == "__main__":
    unittest.main()
