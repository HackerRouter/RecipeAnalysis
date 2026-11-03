"""方块变换适配器与形状识别。

两条判据靠测试钉住：

1. `offset` 区分「源方块」与「环境前提」——把 `tag:minecraft:air` 当源方块，
   「泥土 → 耕地」就变成「空气 → 耕地」，路径必断
2. 顶层是数组的只有这一族，但不能只凭「是数组」就认，还要看条目里有
   `block_state_provider`
"""

from __future__ import annotations

import unittest

from oa.adapters.block_transform import (
    _ShapeError,
    _resolve_then,
    _walk_predicate,
)
from oa.probe.shapes import BLOCK_TRANSFORM, classify


from tests.support import pack, why

class ClassifyTest(unittest.TestCase):
    def test_entry_array_is_block_transform(self) -> None:
        doc = [{"block_state_provider": {"type": "minecraft:rule_based", "rules": []}}]
        self.assertEqual(classify(doc), BLOCK_TRANSFORM)

    def test_array_without_provider_is_not(self) -> None:
        """只有「是数组」不够：结构模板的调色板也是数组。"""
        self.assertNotEqual(classify([{"values": ["a"]}]), BLOCK_TRANSFORM)

    def test_mixed_array_is_not(self) -> None:
        doc = [{"block_state_provider": {}}, {"something": 1}]
        self.assertNotEqual(classify(doc), BLOCK_TRANSFORM)

    def test_empty_array_is_not(self) -> None:
        self.assertNotEqual(classify([]), BLOCK_TRANSFORM)


class PredicateTest(unittest.TestCase):
    def test_matching_blocks_is_source(self) -> None:
        source: list[str] = []
        soft: list[str] = []
        _walk_predicate(
            {"type": "minecraft:matching_blocks", "blocks": "minecraft:oak_wood"},
            "/p",
            source,
            soft,
        )
        self.assertEqual(source, ["block:minecraft:oak_wood"])
        self.assertEqual(soft, [])

    def test_tag_without_offset_is_source(self) -> None:
        source: list[str] = []
        soft: list[str] = []
        _walk_predicate(
            {"type": "minecraft:matching_block_tag", "tag": "minecraft:turns_into_farmland"},
            "/p",
            source,
            soft,
        )
        self.assertEqual(source, ["tag:minecraft:turns_into_farmland"])
        self.assertEqual(soft, [])

    def test_tag_with_offset_is_environment_not_source(self) -> None:
        """「上方是空气」是环境前提。当成源方块会让路径指向空气。"""
        source: list[str] = []
        soft: list[str] = []
        _walk_predicate(
            {
                "type": "minecraft:matching_block_tag",
                "tag": "minecraft:air",
                "offset": [0, 1, 0],
            },
            "/p",
            source,
            soft,
        )
        self.assertEqual(source, [])
        self.assertEqual(soft, ["above=tag:minecraft:air"])

    def test_all_of_splits_source_and_environment(self) -> None:
        source: list[str] = []
        soft: list[str] = []
        _walk_predicate(
            {
                "type": "minecraft:all_of",
                "predicates": [
                    {"type": "minecraft:matching_block_tag", "tag": "minecraft:turns_into_farmland"},
                    {"type": "minecraft:matching_block_tag", "tag": "minecraft:air", "offset": [0, 1, 0]},
                ],
            },
            "/p",
            source,
            soft,
        )
        self.assertEqual(source, ["tag:minecraft:turns_into_farmland"])
        self.assertEqual(soft, ["above=tag:minecraft:air"])

    def test_unknown_predicate_raises(self) -> None:
        with self.assertRaises(_ShapeError):
            _walk_predicate({"type": "minecraft:not_a_real_one"}, "/p", [], [])

    def test_unknown_field_raises(self) -> None:
        """红线：未知字段不得忽略。"""
        with self.assertRaises(_ShapeError):
            _walk_predicate(
                {
                    "type": "minecraft:matching_blocks",
                    "blocks": "minecraft:stone",
                    "surprise": 1,
                },
                "/p",
                [],
                [],
            )

    def test_blocks_array_raises(self) -> None:
        """实测 `blocks` 恒为单字符串；数组形态语义未确认，不许猜。"""
        with self.assertRaises(_ShapeError):
            _walk_predicate(
                {"type": "minecraft:matching_blocks", "blocks": ["minecraft:stone"]},
                "/p",
                [],
                [],
            )


class ThenTest(unittest.TestCase):
    def test_copy_properties(self) -> None:
        target, props = _resolve_then(
            {
                "type": "minecraft:copy_properties",
                "source": {"id": "minecraft:stripped_oak_log", "properties": {"axis": "y"}},
            },
            "/t",
        )
        self.assertEqual(target, "block:minecraft:stripped_oak_log")
        self.assertEqual(props, {"axis": "y"})

    def test_bare_id(self) -> None:
        target, props = _resolve_then({"id": "minecraft:farmland", "properties": {"moisture": "0"}}, "/t")
        self.assertEqual(target, "block:minecraft:farmland")
        self.assertEqual(props, {"moisture": "0"})

    def test_bare_id_without_properties(self) -> None:
        target, props = _resolve_then({"id": "minecraft:dirt"}, "/t")
        self.assertEqual(target, "block:minecraft:dirt")
        self.assertEqual(props, {})

    def test_unknown_type_raises(self) -> None:
        with self.assertRaises(_ShapeError):
            _resolve_then({"type": "minecraft:teleport"}, "/t")


def _pack(label: str):
    return pack(label)


def _ingest(label: str, pack):
    from tests.support import store

    return store(label)


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class CodeTableIntegrationTest(unittest.TestCase):
    """1.18.2 的方块变换硬编码在静态表里，需从代码抽取。

    同一语义在 26.3 走数据包（`block_transform` 的 `transformer_kind=registry`），
    两版共用同一事实种类与 payload 形状。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest("1.18.2", _pack("1.18.2"))

    def facts(self) -> list:
        return self.store.of_kind("block_transform")

    def test_all_tables_found(self) -> None:
        tables = {
            fact.payload["transformer"].split("#")[1] for fact in self.facts()
        }
        self.assertEqual(
            tables,
            {
                "STRIPPABLES",
                "WAXABLES",
                "WAX_OFF_BY_BLOCK",
                "FLATTENABLES",
                "TILLABLES",
                "NEXT_BY_BLOCK",
                "PREVIOUS_BY_BLOCK",
            },
        )

    def test_stripping_direction(self) -> None:
        """方向必须是「原木 → 去皮原木」，不是反过来。"""
        stripped = [
            f.payload
            for f in self.facts()
            if f.payload["transformer"].endswith("#STRIPPABLES")
        ]
        self.assertEqual(len(stripped), 16)
        for payload in stripped:
            self.assertFalse(
                payload["from"][0].split(":")[-1].startswith("stripped_"),
                f"源方块不该是已去皮的：{payload['from']}",
            )
            self.assertTrue(payload["to"].split(":")[-1].startswith("stripped_"))

    def test_inverse_tables_are_flipped(self) -> None:
        """反向表的方向必须与原表相反，不能照抄。"""
        forward = {
            p.payload["from"][0]: p.payload["to"]
            for p in self.facts()
            if p.payload["transformer"].endswith("#WAXABLES")
        }
        inverse = {
            p.payload["from"][0]: p.payload["to"]
            for p in self.facts()
            if p.payload["transformer"].endswith("#WAX_OFF_BY_BLOCK")
        }
        self.assertEqual(len(forward), len(inverse))
        for source, target in forward.items():
            # 打蜡 A→B，去蜡必须 B→A
            self.assertEqual(inverse.get(target), source, f"{source} 的反向不对")

    def test_modes_are_labelled(self) -> None:
        modes = {f.payload["mode"] for f in self.facts()}
        self.assertEqual(modes, {"table", "inverse"})

    def test_unresolved_tables_are_reported(self) -> None:
        """构造器驱动的表抽不出来，必须落进台账，不能静默少抽。"""
        notes = [
            row.note
            for row in self.store.ledger.rows
            if row.rule == "idiom block_transform_tables 说明" and row.note
        ]
        self.assertTrue(notes)
        joined = "\n".join(notes)
        self.assertIn("POTTED_BY_CONTENT", joined)
        self.assertIn("BLOCK_BY_HOST_BLOCK", joined)


if __name__ == "__main__":
    unittest.main()
