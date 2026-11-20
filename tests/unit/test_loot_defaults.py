"""`exploration_map` 默认目的地的源码解析与补写。

两件事分别钉住：

- 解析：只在 loot 函数源码里出现，索引收不到（它不带获取语义锚点），要按文件名找
- 补写：只补没有 `destination` 的条目，并打 `map_destination_default` 标记；
  默认标签不在 `tag` 事实里时一个也不补
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra.adapters.source.loot_defaults import (
    apply_default_destination,
    exploration_map_default,
)
from ra.facts import Fact, FactStore, Prov

JAVA = """package net.minecraft.world.level.storage.loot.functions;

public class ExplorationMapFunction {
    public static final TagKey<ConfiguredStructureFeature<?, ?>> DEFAULT_FEATURE
        = ConfiguredStructureTags.ON_TREASURE_MAPS;
}
"""


def _java_root(text: str = JAVA) -> Path:
    directory = tempfile.mkdtemp()
    path = Path(directory) / "net" / "minecraft" / "world" / "level" / "storage" / "loot" / "functions"
    path.mkdir(parents=True)
    (path / "ExplorationMapFunction.java").write_text(text, encoding="utf-8")
    return Path(directory)


def _store(with_tag: bool = True) -> FactStore:
    store = FactStore(label="test")
    if with_tag:
        store.add(
            Fact(
                kind="tag",
                payload={
                    "tag": "minecraft:on_treasure_maps",
                    "registry": "minecraft:worldgen/configured_structure_feature",
                    "values": ["minecraft:buried_treasure"],
                    "nested": [],
                    "replace": False,
                },
                prov=Prov(input="src", file="data/minecraft/tags/worldgen/configured_structure_feature/on_treasure_maps.json"),
            )
        )
    store.add(
        Fact(
            kind="loot_table",
            payload={
                "table": "minecraft:chests/shipwreck_map",
                "pools": [
                    {
                        "entries": [
                            {
                                "kind": "item",
                                "name": "minecraft:map",
                                "product_id": "minecraft:filled_map",
                                "functions": [{"function": "minecraft:exploration_map"}],
                            }
                        ]
                    }
                ],
            },
            prov=Prov(input="src", file="data/minecraft/loot_tables/chests/shipwreck_map.json"),
        )
    )
    return store


def _entry(store: FactStore) -> dict:
    fact = store.of_kind("loot_table")[0]
    return fact.payload["pools"][0]["entries"][0]


class ExplorationMapDefaultTest(unittest.TestCase):
    def test_constant_is_read_from_source(self) -> None:
        self.assertEqual(exploration_map_default(_java_root()), "minecraft:on_treasure_maps")

    def test_absent_constant_yields_none(self) -> None:
        text = "public class ExplorationMapFunction { int x = 1; }"
        self.assertIsNone(exploration_map_default(_java_root(text)))

    def test_missing_file_yields_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(exploration_map_default(Path(tmp)))

    def test_default_is_filled_with_flag(self) -> None:
        store = _store()
        filled, unresolved = apply_default_destination(store, "minecraft:on_treasure_maps")
        self.assertEqual((filled, unresolved), (1, 0))
        entry = _entry(store)
        self.assertEqual(entry["map_destination"], "#minecraft:on_treasure_maps")
        self.assertEqual(entry["map_structures"], ["minecraft:buried_treasure"])
        self.assertIs(entry["map_destination_default"], True)

    def test_entries_with_destination_are_untouched(self) -> None:
        store = _store()
        entry = _entry(store)
        entry["map_destination"] = "#minecraft:on_abandoned_camp_swamp"
        entry["map_structures"] = ["minecraft:abandoned_camp_swamp"]
        filled, _ = apply_default_destination(store, "minecraft:on_treasure_maps")
        self.assertEqual(filled, 0)
        entry = _entry(store)
        self.assertEqual(entry["map_destination"], "#minecraft:on_abandoned_camp_swamp")
        self.assertNotIn("map_destination_default", entry)

    def test_unknown_tag_is_not_guessed(self) -> None:
        store = _store(with_tag=False)
        filled, unresolved = apply_default_destination(store, "minecraft:on_treasure_maps")
        self.assertEqual((filled, unresolved), (0, 1))
        self.assertNotIn("map_destination", _entry(store))


if __name__ == "__main__":
    unittest.main()
