"""结构布局的三张可查表。

判据：

- 给定 `minecraft:village_plains` 能列出全部池、模板与权重
- 容器表只给身份（模板 + 坐标 + 战利品表），不给数量
- 方块表带完整状态串，且同一状态的格数可查
"""

from __future__ import annotations

import unittest

from tests.support import pack, why


def _store(label: str):
    from tests.support import store

    return store(label)


def _tables(label: str):
    from ra.report.structure_tables import build_structure_tables

    return build_structure_tables(_store(label))


class StructureTablesBase:
    label = ""
    tables: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.tables = _tables(cls.label)

    def structures(self) -> list[dict]:
        return self.tables["structures"]

    def containers(self) -> list[dict]:
        return self.tables["template_containers"]

    def blocks(self) -> list[dict]:
        return self.tables["template_blocks"]

    def test_tables_are_not_empty(self) -> None:
        for name in ("structures", "template_containers", "template_blocks"):
            self.assertTrue(self.tables[name], name)

    def test_village_plains_lists_all_pools(self) -> None:
        row = next(
            (item for item in self.structures() if item["structure"] == "minecraft:village_plains"),
            None,
        )
        self.assertIsNotNone(row, "村庄结构必须有一行")
        pools = {item["pool"] for item in row["pools"]}
        self.assertIn("minecraft:village/plains/town_centers", pools)
        self.assertIn("minecraft:village/plains/houses", pools)
        self.assertIn("minecraft:village/plains/streets", pools)

    def test_weights_are_recorded(self) -> None:
        row = next(
            item for item in self.structures() if item["structure"] == "minecraft:village_plains"
        )
        for pool in row["pools"]:
            total = pool["weight_total"]
            if pool["templates"]:
                self.assertGreater(total, 0, pool["pool"])
            for template in pool["templates"]:
                self.assertGreaterEqual(template["weight"], 1)
                self.assertTrue(template["template"])

    def test_containers_carry_identity_only(self) -> None:
        for row in self.containers():
            self.assertTrue(row["template"])
            self.assertTrue(row["table"].startswith("minecraft:"))
            self.assertIsInstance(row["pos"], list)
            self.assertNotIn("count", row, "容器表只给身份，不给数量")

    def test_village_house_chest_is_listed(self) -> None:
        found = [
            row
            for row in self.containers()
            if row["template"] == "village/plains/houses/plains_big_house_1"
        ]
        self.assertTrue(found)
        self.assertIn(
            "minecraft:chests/village/village_plains_house",
            {row["table"] for row in found},
        )

    def test_block_states_are_split(self) -> None:
        for row in self.blocks():
            self.assertNotIn("{", row["block"])
            self.assertGreaterEqual(row["count"], 1)
            if row["state"] is not None:
                self.assertNotIn("{", row["state"])
                self.assertNotIn("}", row["state"])

    def test_door_state_is_static(self) -> None:
        """门的上/下半是静态可定的，不需要测世界分布。"""
        states = {
            row["state"]
            for row in self.blocks()
            if row["block"] == "minecraft:oak_door"
        }
        self.assertTrue(any("half:" in (state or "") for state in states))


@unittest.skipUnless(pack("26.3"), why("26.3"))
class StructureTables263Test(StructureTablesBase, unittest.TestCase):
    label = "26.3"


@unittest.skipUnless(pack("1.18.2"), why("1.18.2"))
class StructureTables1182Test(StructureTablesBase, unittest.TestCase):
    label = "1.18.2"


if __name__ == "__main__":
    unittest.main()
