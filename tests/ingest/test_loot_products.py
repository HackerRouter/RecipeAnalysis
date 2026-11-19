"""战利品条目的「修饰后产物身份」。

`exploration_map` 会把空地图改写成具体地图。两版写法不同：

| 版本 | 条目 `name` | 修饰后 |
|---|---|---|
| 26.3 | `minecraft:abandoned_camp_map` | 同名（数据里已写具体地图） |
| 1.18.2 | `minecraft:map` | `minecraft:filled_map` |

事实的 `product_id` 一律记修饰后的身份，`name` 保持数据原样；
destinations 另记 `map_destination`，供下游按目的地展开。
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


if __name__ == "__main__":
    unittest.main()
