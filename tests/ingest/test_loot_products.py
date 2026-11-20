"""战利品条目的「修饰后产物身份」。

`exploration_map` 会把空地图改写成具体地图。两版写法不同：

| 版本 | 条目 `name` | 修饰后 |
|---|---|---|
| 26.3 | `minecraft:abandoned_camp_map` | 同名（数据里已写具体地图） |
| 1.18.2 | `minecraft:map` | `minecraft:filled_map` |

事实的 `product_id` 一律记修饰后的身份，`name` 保持数据原样；
destinations 另记 `map_destination`（标签原文）与 `map_structures`（展开后的结构）。
旧版数据不写 `destination`，默认值由源码补回，带 `map_destination_default` 标记。
"""

from __future__ import annotations

import unittest

from tests.support import pack, store, why


def _entries(label: str, suffix: str) -> list[dict]:
    rows = []
    for fact in store(label).of_kind("loot_table"):
        if not fact.prov.file.endswith(suffix):
            continue
        for pool in fact.payload.get("pools") or ():
            for entry in pool.get("entries") or ():
                if isinstance(entry, dict):
                    rows.append(entry)
    return rows


class _ProductBase:
    label = ""

    def entries_with_product(self) -> list[dict]:
        raise NotImplementedError

    def test_product_id_present(self) -> None:
        entries = self.entries_with_product()
        self.assertTrue(entries)
        for entry in entries:
            self.assertTrue(entry["product_id"].startswith("minecraft:"))

    def test_non_map_entries_carry_no_product(self) -> None:
        for entry in self.entries_with_product():
            if entry.get("product_id") is None:
                self.assertNotIn("map_destination", entry)


@unittest.skipUnless(pack("26.3"), why("26.3"))
class Product263Test(_ProductBase, unittest.TestCase):
    label = "26.3"

    def entries_with_product(self) -> list[dict]:
        entries = _entries(self.label, "chests/abandoned_camp_common_chest.json")
        return [entry for entry in entries if entry.get("product_id")]

    def test_typed_maps_keep_their_identity(self) -> None:
        products = {entry["product_id"] for entry in self.entries_with_product()}
        self.assertEqual(products, {"minecraft:abandoned_camp_map"})

    def test_destination_is_recorded(self) -> None:
        for entry in self.entries_with_product():
            self.assertTrue(entry["map_destination"].startswith("#minecraft:on_abandoned_camp"))

    def test_destination_tag_is_resolved_to_structures(self) -> None:
        """目的地是结构标签，产物对得上的是结构 id。

        26.3 的 `destination` 写成 `#minecraft:on_abandoned_camp_bamboo_jungle`，
        展开后必须是 `minecraft:abandoned_camp_bamboo_jungle`。只给标签名，
        下游得自己再查一遍 tag 事实，两边各实现一份就会有两个答案。
        """
        for entry in self.entries_with_product():
            structures = entry["map_structures"]
            self.assertEqual(len(structures), 1, entry["map_destination"])
            self.assertTrue(structures[0].startswith("minecraft:abandoned_camp"))

    def test_every_map_knows_its_structure(self) -> None:
        """全量地图条目都能展开：留空说明某条标签不在 tag 事实里。"""
        empty: list[tuple[str, str]] = []
        for fact in store(self.label).of_kind("loot_table"):
            for pool in fact.payload.get("pools") or ():
                for entry in pool.get("entries") or ():
                    if entry.get("product_id") and not entry.get("map_structures"):
                        empty.append((str(fact.payload.get("table")), str(entry.get("name"))))
        self.assertEqual(empty, [])


@unittest.skipUnless(pack("1.18.2"), why("1.18.2"))
class Product1182Test(_ProductBase, unittest.TestCase):
    label = "1.18.2"

    def entries_with_product(self) -> list[dict]:
        entries = _entries(self.label, "chests/shipwreck_map.json")
        return [entry for entry in entries if entry.get("product_id")]

    def test_empty_map_becomes_filled_map(self) -> None:
        products = {entry["product_id"] for entry in self.entries_with_product()}
        self.assertEqual(products, {"minecraft:filled_map"})
        self.assertEqual(
            {entry["name"] for entry in self.entries_with_product()},
            {"minecraft:map"},
        )

    def test_default_destination_is_filled_from_source(self) -> None:
        """该版数据里没有 `destination`，默认值写在 loot 函数源码里。

        `ExplorationMapFunction.DEFAULT_FEATURE = ConfiguredStructureTags.ON_TREASURE_MAPS`，
        序列化时等于默认值就省略。所以数据里缺这个键本身就是信息，
        补上的字段带 `map_destination_default` 与数据里写明的区分开。
        """
        for entry in self.entries_with_product():
            self.assertEqual(entry["map_destination"], "#minecraft:on_treasure_maps")
            self.assertEqual(entry["map_structures"], ["minecraft:buried_treasure"])
            self.assertIs(entry["map_destination_default"], True)


if __name__ == "__main__":
    unittest.main()
