"""刷怪表的导出。

判据：

- 四处来源都进同一张表，`holder_kind` 区分
- 权重与数量照原样，不折算成概率
- 两版的结构覆盖刷怪完全相同（机制没变）
- 行序稳定，重复运行逐字节一致
"""

from __future__ import annotations

import unittest

from tests.support import pack, store, why

FOUR_KINDS = {"biome", "structure", "trial_spawner", "structure_template", "raid"}
THREE_KINDS = {"biome", "structure", "structure_template", "raid"}


class _SpawnBase:
    label = ""
    tables: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        from ra.report.spawn_tables import build_spawn_tables

        cls.tables = build_spawn_tables(store(cls.label))

    def rows(self) -> list[dict]:
        return self.tables["spawn_tables"]

    def rows_of(self, kind: str) -> list[dict]:
        return [row for row in self.rows() if row["holder_kind"] == kind]

    def test_table_is_not_empty(self) -> None:
        self.assertTrue(self.rows(), "刷怪表为空")

    def test_biome_rows_carry_weight_and_count(self) -> None:
        rows = self.rows_of("biome")
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row["holder"].startswith("biome:minecraft:"), row)
            self.assertIsInstance(row["weight"], int, row)
            self.assertIsInstance(row["count_min"], int, row)
            self.assertIsInstance(row["count_max"], int, row)
            self.assertLessEqual(row["count_min"], row["count_max"], row)

    def test_nether_fortress_matches_across_versions(self) -> None:
        """下界要塞的刷怪覆盖两版一致：权重与数量都对得上。"""
        rows = [
            row for row in self.rows_of("structure")
            if row["holder"] == "structure:minecraft:fortress"
        ]
        got = {(row["entity"], row["category"], row["weight"], row["count_min"], row["count_max"]) for row in rows}
        self.assertEqual(
            got,
            {
                ("minecraft:blaze", "monster", 10, 2, 3),
                ("minecraft:zombified_piglin", "monster", 5, 4, 4),
                ("minecraft:wither_skeleton", "monster", 8, 5, 5),
                ("minecraft:skeleton", "monster", 2, 5, 5),
                ("minecraft:magma_cube", "monster", 3, 4, 4),
            },
        )

    def test_template_spawner_rows(self) -> None:
        rows = self.rows_of("structure_template")
        entities = {row["entity"] for row in rows}
        self.assertIn("minecraft:spider", entities, "林地府邸模板里有刷怪笼")
        for row in rows:
            self.assertIsInstance(row["weight"], int, row)
            self.assertIsNone(row["count_min"], "模板 NBT 不写每次数量")

    def test_rows_are_sorted(self) -> None:
        keys = [
            (
                row["holder_kind"],
                row["holder"],
                row["wave"] if row["wave"] is not None else -1,
                row["category"] or "",
                row["entity"],
            )
            for row in self.rows()
        ]
        self.assertEqual(keys, sorted(keys))

    def test_raid_waves_keep_wave_numbers(self) -> None:
        """波次是难度建模的输入，不能只留「会不会刷」。"""
        rows = [
            row for row in self.rows_of("raid")
            if row["entity"] == "minecraft:pillager"
        ]
        got = {row["wave"]: row["count_min"] for row in rows}
        self.assertEqual(
            got,
            {1: 4, 2: 3, 3: 3, 4: 4, 5: 4, 6: 4, 7: 2},
            "袭击波次表是 RaiderType 的数组，第 0 位不用",
        )
        for row in self.rows_of("raid"):
            self.assertEqual(row["requires"], "assume:raid")
            self.assertIsNotNone(row["wave"])
            self.assertIsNone(row["weight"], "袭击按波次定数量，没有权重")


@unittest.skipUnless(pack("26.3"), why("26.3"))
class SpawnTables263Test(_SpawnBase, unittest.TestCase):
    label = "26.3"

    def test_all_holder_kinds(self) -> None:
        self.assertEqual({row["holder_kind"] for row in self.rows()}, FOUR_KINDS)

    def test_trial_spawner_holder_is_namespaced(self) -> None:
        for row in self.rows_of("trial_spawner"):
            self.assertTrue(row["holder"].startswith("trial_spawner:minecraft:"), row)
            self.assertIsNone(row["category"], "tier 不是刷怪类别，不进 category")

    def test_ominous_trial_requires_bad_omen(self) -> None:
        """不祥配置只在玩家带不祥之兆（bad_omen / trial_omen）时启用。"""
        for row in self.rows_of("trial_spawner"):
            if "/ominous" in row["holder"]:
                self.assertEqual(row["requires"], "assume:ominous", row)
            else:
                self.assertIsNone(row["requires"], row)


@unittest.skipUnless(pack("1.18.2"), why("1.18.2"))
class SpawnTables1182Test(_SpawnBase, unittest.TestCase):
    label = "1.18.2"

    def test_no_trial_spawner(self) -> None:
        """试炼刷怪笼是 1.21 引入的；旧版没有这一族是正确结果。"""
        self.assertEqual({row["holder_kind"] for row in self.rows()}, THREE_KINDS)


if __name__ == "__main__":
    unittest.main()
