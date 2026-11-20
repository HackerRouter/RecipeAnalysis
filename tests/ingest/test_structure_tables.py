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

    def code_containers(self) -> list[dict]:
        return self.tables["structure_containers"]

    def test_tables_are_not_empty(self) -> None:
        for name in (
            "structures",
            "template_containers",
            "template_blocks",
            "structure_containers",
        ):
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
            if row["table"] is None:
                self.assertEqual(row.get("loot_bound"), "code", row["template"])
            else:
                self.assertTrue(row["table"].startswith("minecraft:"))
            self.assertNotIn("count", row, "容器表只给身份，不给数量")
            if row.get("via") == "template":
                self.assertIsInstance(row["pos"], list)
            else:
                self.assertIsNone(row["pos"], "处理器注入的容器没有坐标")

    def test_code_bound_containers_are_listed(self) -> None:
        """模板里有容器、表不在 NBT 里的结构必须出行，否则会被读成「没有容器」。"""
        families = {
            row["template"].split("/", 1)[0]
            for row in self.containers()
            if row.get("loot_bound") == "code"
        }
        self.assertIn("shipwreck", families)
        self.assertIn("end_city", families)

    def test_slot_holders_are_not_containers(self) -> None:
        """篝火、熔炉也带物品槽，但不承载战利品表，不得计入容器。"""
        kinds = {row["block_entity"] for row in self.containers()}
        self.assertNotIn("minecraft:campfire", kinds)
        self.assertNotIn("minecraft:furnace", kinds)
        self.assertNotIn("minecraft:brewing_stand", kinds)

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

    def test_template_markers_are_attached_to_their_block_row(self) -> None:
        """模板里的数据标记名挂在 `structure_block{mode:data}` 行上。

        海军遗构的溺尸只写在标记的 `metadata` 里：不看它，白名单里只有一堆
        `structure_block{mode:data}`，看不出那里会冒出什么。
        """
        marked = [row for row in self.blocks() if row.get("markers")]
        self.assertTrue(marked)
        for row in marked:
            self.assertEqual(row["block"], "minecraft:structure_block", row["template"])
            self.assertTrue(str(row["state"]).startswith("mode:data"), row["template"])
            self.assertIsInstance(row["markers"], list)

    def test_ocean_ruin_markers_name_the_drowned(self) -> None:
        rows = [row for row in self.blocks() if row["template"] == "underwater_ruin/big_brick_1"]
        markers = {marker for row in rows for marker in row.get("markers", [])}
        self.assertEqual(markers, {"chest", "drowned"})

    def test_marker_names_are_not_a_block_of_their_own(self) -> None:
        """标记不拆成单独的行：同一格既是一个方块也是一个标记，拆行会重复计 `count`。"""
        from tests.support import store

        expected: dict[str, int] = {}
        unreadable: set[str] = set()
        for fact in store(self.label).of_kind("template"):
            template = fact.payload.get("template")
            expected[template] = int(fact.payload.get("block_count") or 0)
            if fact.payload.get("blocks_unreadable"):
                unreadable.add(template)
        actual: dict[str, int] = {}
        for row in self.blocks():
            if row["template"] in unreadable:
                # palette 不可读，只剩标记那行；它不对应 `block_counts`
                continue
            actual[row["template"]] = actual.get(row["template"], 0) + row["count"]
        for template, total in actual.items():
            self.assertEqual(total, expected.get(template), template)

    def test_code_containers_join_worldgen(self) -> None:
        """代码侧容器行必须回连到世界生成事实里的结构 id。"""
        for row in self.code_containers():
            self.assertTrue(row["structures"], row["structure_type"])
            self.assertTrue(row["table"].startswith("minecraft:"))
            self.assertGreaterEqual(row["sites"], 1)
            self.assertTrue(row["sources"], row["structure_type"])

    def test_template_less_structure_has_code_containers(self) -> None:
        """要塞没有任何模板，三张模板表里一条也不会有，只能靠代码侧那张。"""
        rows = [
            row
            for row in self.code_containers()
            if row["structure_type"] == "minecraft:stronghold"
        ]
        self.assertEqual(
            {row["table"] for row in rows},
            {
                "minecraft:chests/stronghold_corridor",
                "minecraft:chests/stronghold_crossing",
                "minecraft:chests/stronghold_library",
            },
        )
        for row in rows:
            self.assertEqual(row["structures"], ["minecraft:stronghold"])
            self.assertEqual(row["container"], "chest")


@unittest.skipUnless(pack("26.3"), why("26.3"))
class StructureTables263Test(StructureTablesBase, unittest.TestCase):
    label = "26.3"

    def test_nested_template_ids_are_complete(self) -> None:
        """`ancient_city/structures/*` 的模板不能被截成裸名。"""
        names = {row["template"] for row in self.containers()}
        self.assertIn("ancient_city/structures/barracks", names)

    def test_processor_injected_containers_are_exported(self) -> None:
        """处理器附加战利品的方块不在模板 NBT 里，必须从处理器定义导出。"""
        rows = [
            row
            for row in self.containers()
            if row.get("via") == "processor" and row["template"].startswith("trail_ruins/")
        ]
        self.assertTrue(rows)
        by_processor = {(row["processor"], row["table"]): row for row in rows}
        common = by_processor[
            ("minecraft:trail_ruins_houses_archaeology", "minecraft:archaeology/trail_ruins_common")
        ]
        rare = by_processor[
            ("minecraft:trail_ruins_houses_archaeology", "minecraft:archaeology/trail_ruins_rare")
        ]
        roads = by_processor[
            ("minecraft:trail_ruins_roads_archaeology", "minecraft:archaeology/trail_ruins_common")
        ]
        self.assertEqual(common["limit"], 6)
        self.assertEqual(rare["limit"], 3)
        self.assertEqual(roads["limit"], 2)
        self.assertEqual(common["block_entity"], "minecraft:suspicious_gravel")
        self.assertIsNone(common["pos"])

    def test_shipwreck_markers_are_exported(self) -> None:
        """船骸按标记选表，标记名与表必须一起导出。"""
        rows = [
            row for row in self.code_containers() if row["structure_type"] == "minecraft:shipwreck"
        ]
        markers = {marker for row in rows for marker in row.get("markers", [])}
        self.assertEqual(markers, {"map_chest", "supply_chest", "treasure_chest"})


@unittest.skipUnless(pack("1.18.2"), why("1.18.2"))
class StructureTables1182Test(StructureTablesBase, unittest.TestCase):
    label = "1.18.2"

    def test_structure_type_ids_are_this_versions(self) -> None:
        """1.18.2 的类型 id 是 `mansion` / `jungle_pyramid`，不是新版的叫法。"""
        types = {row["structure_type"] for row in self.code_containers()}
        self.assertIn("minecraft:mansion", types)
        self.assertIn("minecraft:jungle_pyramid", types)
        self.assertNotIn("minecraft:woodland_mansion", types)


if __name__ == "__main__":
    unittest.main()
