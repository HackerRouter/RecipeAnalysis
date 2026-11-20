"""SNBT 解析。模板是文本 SNBT，不是二进制 NBT，这两者的失败模式不同：
文本解析要么完整解析、要么明确报错；二进制会静默错位。因此这里不泛化。
"""

from __future__ import annotations

import unittest

from ra.adapters.templates import SnbtError, parse_snbt
from ra.mcshared.snbt import normalize_template, template_id_from_file


class TemplateIdTest(unittest.TestCase):
    """模板 ID 取模板根之后的全部路径，不按目录名再切一次。"""

    def test_nested_structures_directory_is_kept(self) -> None:
        # 模板自身含 `structures/` 子目录时，旧的按子串切法会截成 `barracks`
        self.assertEqual(
            template_id_from_file("data/minecraft/structure/ancient_city/structures/barracks.snbt"),
            "ancient_city/structures/barracks",
        )

    def test_top_level_template(self) -> None:
        self.assertEqual(
            template_id_from_file("data/minecraft/structure/empty.snbt"), "empty"
        )

    def test_plural_template_dir(self) -> None:
        self.assertEqual(
            template_id_from_file("data/minecraft/structures/village/plains/house.snbt"),
            "village/plains/house",
        )


class SnbtTest(unittest.TestCase):
    def test_real_template_shape(self) -> None:
        text = (
            '{ size: [1,3,1], data: [ {pos:[0,0,0], state:"", '
            'nbt:{id:"minecraft:jigsaw", pool:"minecraft:empty", final_state:"minecraft:air"}}, '
            '{pos:[0,1,0], state:"minecraft:stone"} ], '
            'entities: [ {blockPos:[0,1,0], pos:[0.5,1.0,0.5], '
            'nbt:{Health:10.0f, HandItems:[{},{},...]}} ], palette: [""] }'
        )
        doc = parse_snbt(text)
        self.assertEqual(doc["size"], [1, 3, 1])
        self.assertEqual(doc["data"][0]["nbt"]["pool"], "minecraft:empty")
        self.assertEqual(doc["data"][1]["state"], "minecraft:stone")
        self.assertAlmostEqual(doc["entities"][0]["nbt"]["Health"], 10.0)

    def test_unquoted_keys_and_nested_lists(self) -> None:
        doc = parse_snbt("{a:{b:[1,2,{c:3}]}}")
        self.assertEqual(doc["a"]["b"][2]["c"], 3)

    def test_quoted_keys_with_separators(self) -> None:
        doc = parse_snbt('{"minecraft:foo": 1, \'bar baz\': 2}')
        self.assertEqual(doc["minecraft:foo"], 1)
        self.assertEqual(doc["bar baz"], 2)

    def test_typed_array_prefix(self) -> None:
        doc = parse_snbt("{v:[I;1,2,3]}")
        self.assertEqual(doc["v"], [1, 2, 3])

    def test_booleans(self) -> None:
        doc = parse_snbt("{a:trueb, b:false}")
        self.assertIs(doc["a"], True)
        self.assertIs(doc["b"], False)

    def test_unclosed_compound_raises(self) -> None:
        with self.assertRaises(SnbtError):
            parse_snbt("{a:1")

    def test_trailing_content_raises(self) -> None:
        with self.assertRaises(SnbtError):
            parse_snbt("{a:1} junk")


class MarkerTest(unittest.TestCase):
    """`structure_block{mode:data}` 的 `metadata` 才是标记名。

    这是模板里唯一不以方块表达机制的地方：海军遗构的溺尸、船骸的三种箱子
    都靠它。`mode` 是状态、`metadata` 才是标记名，两者不能混。
    """

    def test_metadata_becomes_markers(self) -> None:
        text = (
            '{size:[1,3,1],palette:["minecraft:stone"],data:['
            '{pos:[0,0,0],state:"minecraft:structure_block{mode:data}",'
            'nbt:{id:"minecraft:structure_block",metadata:"drowned",mode:"DATA"}},'
            '{pos:[0,1,0],state:"minecraft:structure_block{mode:data}",'
            'nbt:{id:"minecraft:structure_block",metadata:"chest",mode:"DATA"}},'
            '{pos:[0,2,0],state:"minecraft:stone"}]}'
        )
        payload, _ = normalize_template(parse_snbt(text), "underwater_ruin/big_brick_1")
        self.assertEqual(payload["markers"], ["chest", "drowned"])
        self.assertEqual(payload["marker_cells"], 2)

    def test_empty_metadata_counts_but_adds_no_name(self) -> None:
        """名字没写的标记也是一处标记，不能被当成普通方块。"""
        text = (
            '{size:[1,1,1],palette:["minecraft:stone"],data:['
            '{pos:[0,0,0],state:"minecraft:structure_block{mode:data}",'
            'nbt:{id:"minecraft:structure_block",metadata:"",mode:"DATA"}}]}'
        )
        payload, _ = normalize_template(parse_snbt(text), "x")
        self.assertEqual(payload["markers"], [])
        self.assertEqual(payload["marker_cells"], 1)

    def test_other_block_entities_are_not_markers(self) -> None:
        text = (
            '{size:[1,1,1],palette:["minecraft:chest"],data:['
            '{pos:[0,0,0],state:"minecraft:chest",'
            'nbt:{id:"minecraft:chest",LootTable:"minecraft:chests/x"}}]}'
        )
        payload, _ = normalize_template(parse_snbt(text), "x")
        self.assertEqual(payload["marker_cells"], 0)


if __name__ == "__main__":
    unittest.main()
