"""世界生成的约束子树不是产物。

`replaceable_blocks` 一类键列的是「什么可以被覆盖」，形状与随机放置提供者
同为 `{"type": "matching_blocks", "blocks": [...]}`。只按键名 `blocks` 取值，
会把整张白名单编译成 `seeds` 规则，例如「`chorus_plant` 来自下界菌类」。
"""

from __future__ import annotations

import unittest

from ra.adapters.worldgen import CONSTRAINT_KEYS, _collect_refs


def _refs(doc: dict) -> list[dict]:
    out: list[dict] = []
    _collect_refs(doc, out, depth=0)
    return out


class ConstraintSubtreeTest(unittest.TestCase):
    def test_replaceable_blocks_is_not_a_placement(self) -> None:
        refs = _refs(
            {
                "type": "minecraft:huge_fungus",
                "stem_state": {"Name": "minecraft:crimson_stem"},
                "replaceable_blocks": {
                    "type": "minecraft:matching_blocks",
                    "blocks": ["minecraft:chorus_plant", "minecraft:crimson_fungus"],
                },
            }
        )
        ids = {ref["id"] for ref in refs}
        self.assertIn("minecraft:crimson_stem", ids)
        self.assertNotIn("minecraft:chorus_plant", ids)
        self.assertNotIn("minecraft:crimson_fungus", ids)

    def test_random_block_provider_still_records_placement(self) -> None:
        """`blocks` 在放置提供者里仍是候选表，屏蔽不能按后缀通配误伤。"""
        refs = _refs(
            {"to_place": {"type": "minecraft:random_block", "blocks": "#minecraft:corals"}}
        )
        self.assertIn({"slot": "tag", "id": "minecraft:corals"}, refs)

    def test_geode_constraints_are_skipped_but_inner_placements_kept(self) -> None:
        refs = _refs(
            {
                "blocks": {
                    "inner_placements": ["minecraft:small_amethyst_bud"],
                    "cannot_replace": {
                        "type": "minecraft:matching_blocks",
                        "blocks": ["minecraft:bedrock"],
                    },
                    "invalid_blocks": "#minecraft:geode_invalid_blocks",
                }
            }
        )
        self.assertEqual(refs, [{"slot": "block", "id": "minecraft:small_amethyst_bud"}])

    def test_boolean_and_numeric_switches_are_not_constraint_keys(self) -> None:
        """`replace_with_blackstone`、`invalid_blocks_threshold` 不表达方块集合。"""
        self.assertNotIn("replace_with_blackstone", CONSTRAINT_KEYS)
        self.assertNotIn("invalid_blocks_threshold", CONSTRAINT_KEYS)


if __name__ == "__main__":
    unittest.main()
