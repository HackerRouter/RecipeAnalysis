"""刷怪来源的语法归一：两版的字段差异都在这一层吸收。"""

from __future__ import annotations

import unittest

from ra.adapters.templates import _spawner_potentials
from ra.adapters.worldgen import _biome_spawns, _spawn_count, _spawn_entry


class SpawnCountTest(unittest.TestCase):
    def test_fixed_count(self) -> None:
        self.assertEqual(_spawn_count({"count": 4}), (4, 4))

    def test_uniform_object(self) -> None:
        node = {"count": {"type": "minecraft:uniform", "min_inclusive": 2, "max_inclusive": 3}}
        self.assertEqual(_spawn_count(node), (2, 3))

    def test_legacy_min_max(self) -> None:
        self.assertEqual(_spawn_count({"minCount": 2, "maxCount": 3}), (2, 3))

    def test_absent_is_none_not_one(self) -> None:
        """没写数量与写了一只不是同一件事。"""
        self.assertEqual(_spawn_count({}), (None, None))


class SpawnEntryTest(unittest.TestCase):
    def test_entry_carries_weight_and_category(self) -> None:
        row = _spawn_entry({"type": "minecraft:witch", "weight": 5, "count": 1}, "monster")
        self.assertEqual(
            row,
            {
                "category": "monster",
                "entity": "minecraft:witch",
                "weight": 5,
                "count_min": 1,
                "count_max": 1,
            },
        )

    def test_tag_is_not_an_entity(self) -> None:
        self.assertIsNone(_spawn_entry({"type": "#minecraft:raiders"}, "monster"))


class BiomeSpawnsTest(unittest.TestCase):
    def test_modern_attributes_shape(self) -> None:
        body = {
            "attributes": {
                "minecraft:gameplay/natural_mob_spawns": {
                    "argument": {
                        "spawns_by_category": {
                            "creature": [
                                {"type": "minecraft:sheep", "weight": 12, "count": 4},
                            ]
                        },
                        "spawn_costs": {"minecraft:sheep": {"energy_budget": 0.1}},
                    }
                }
            }
        }
        rows, costs = _biome_spawns(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity"], "minecraft:sheep")
        self.assertEqual(rows[0]["category"], "creature")
        self.assertIn("minecraft:sheep", costs)

    def test_legacy_spawners_shape(self) -> None:
        body = {
            "spawners": {
                "monster": [
                    {"type": "minecraft:zombie", "weight": 95, "minCount": 1, "maxCount": 4}
                ]
            }
        }
        rows, costs = _biome_spawns(body)
        self.assertEqual(rows[0]["count_min"], 1)
        self.assertEqual(rows[0]["count_max"], 4)
        self.assertEqual(costs, {})

    def test_missing_block_is_empty(self) -> None:
        self.assertEqual(_biome_spawns({}), ([], {}))


class TemplateSpawnerTest(unittest.TestCase):
    def test_potentials_win_over_spawn_data(self) -> None:
        """两者并存时只取 SpawnPotentials，免得同一实体出现两次。"""
        doc = {
            "data": [
                {
                    "pos": [4, 1, 3],
                    "nbt": {
                        "id": "minecraft:spawner",
                        "SpawnData": {"entity": {"id": "minecraft:spider"}},
                        "SpawnPotentials": [
                            {"data": {"entity": {"id": "minecraft:spider"}}, "weight": 1}
                        ],
                    },
                }
            ]
        }
        rows = _spawner_potentials(doc)
        self.assertEqual(rows, [{"pos": [4, 1, 3], "entity": "minecraft:spider", "weight": 1}])

    def test_spawn_data_only(self) -> None:
        doc = {
            "data": [
                {
                    "pos": [0, 0, 0],
                    "nbt": {"SpawnData": {"entity": {"id": "minecraft:silverfish"}}},
                }
            ]
        }
        rows = _spawner_potentials(doc)
        self.assertEqual(rows, [{"pos": [0, 0, 0], "entity": "minecraft:silverfish", "weight": None}])

    def test_ordinary_container_is_ignored(self) -> None:
        doc = {"data": [{"pos": [0, 0, 0], "nbt": {"id": "minecraft:chest", "LootTable": "x"}}]}
        self.assertEqual(_spawner_potentials(doc), [])


if __name__ == "__main__":
    unittest.main()
