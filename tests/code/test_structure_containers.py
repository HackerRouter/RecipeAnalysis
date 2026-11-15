"""结构拼装器代码里的容器绑定。

这类表数据包完全不含：下界要塞、要塞、废弃矿井没有模板；船骸、末地城、庄园的
模板有箱子但没有 `LootTable`。判据见
[`docs/shapes.md`](../../../docs/shapes.md) 的「结构容器也可能只存在于生成代码里」。
"""

from __future__ import annotations

import unittest

from ra.adapters.source.idioms.structure_containers import (
    LOOT_CONSTANT,
    REGISTRATION,
    _classify,
    _statement_bounds,
)

from tests.support import pack, why


def _pack(label: str):
    return pack(label)


def _ingest(label: str):
    from tests.support import store

    return store(label)


class RegistrationRegexTest(unittest.TestCase):
    def test_modern_form(self) -> None:
        text = 'StructureType.register("ocean_monument", OceanMonumentStructure.CODEC);'
        self.assertEqual(
            REGISTRATION.findall(text),
            [("StructureType", "ocean_monument", "OceanMonumentStructure")],
        )

    def test_legacy_form(self) -> None:
        text = (
            'StructureFeature.register("mineshaft", new MineshaftFeature('
            "MineshaftConfiguration.CODEC), GenerationStep.Decoration.UNDERGROUND_STRUCTURES);"
        )
        self.assertEqual(
            REGISTRATION.findall(text),
            [("StructureFeature", "mineshaft", "MineshaftFeature")],
        )

    def test_other_registrations_do_not_match(self) -> None:
        """`BuiltinStructures.register("village")` 这类没有类参数，不算结构类型注册。"""
        self.assertEqual(REGISTRATION.findall('BuiltinStructures.register("village");'), [])


class StatementTest(unittest.TestCase):
    def test_statement_is_bounded(self) -> None:
        text = "int a = 0; this.createChest(level, box, random, 1, 2, 3, BuiltInLootTables.X); int b = 1;"
        start, end = _statement_bounds(text, text.index("BuiltInLootTables"))
        self.assertEqual(text[start:end].strip(), "this.createChest(level, box, random, 1, 2, 3, BuiltInLootTables.X);")


class ClassifyTest(unittest.TestCase):
    def test_create_chest(self) -> None:
        self.assertEqual(_classify("this.createChest(l, b, r, 1, 2, 3, BuiltInLootTables.X)")[0], "chest")

    def test_create_dispenser(self) -> None:
        self.assertEqual(
            _classify("this.createDispenser(l, b, r, 1, 2, 3, Direction.NORTH, BuiltInLootTables.X)")[0],
            "dispenser",
        )

    def test_marker_map(self) -> None:
        self.assertEqual(
            _classify('Map.of("supply_chest", BuiltInLootTables.X)')[0], "marker"
        )

    def test_processor(self) -> None:
        self.assertEqual(
            _classify("archyRuleProcessor(Blocks.SAND, Blocks.SUSPICIOUS_SAND, BuiltInLootTables.X)")[0],
            "processor",
        )

    def test_set_loot_table_on_chest(self) -> None:
        """`((ChestBlockEntity)blockEntity).setLootTable(...)` 是箱子。"""
        self.assertEqual(
            _classify("((ChestBlockEntity)blockEntity).setLootTable(BuiltInLootTables.X, r.nextLong())")[0],
            "chest",
        )

    def test_set_loot_table_on_generic_container(self) -> None:
        self.assertEqual(
            _classify(
                "RandomizableContainer.setBlockEntityLootTable(level, random, pos, BuiltInLootTables.X)"
            )[0],
            "block_entity",
        )

    def test_constant_name_does_not_decide_the_shape(self) -> None:
        """`IGLOO_CHEST` 的名字里带 chest，形态仍由调用名判。"""
        self.assertEqual(
            _classify(
                "RandomizableContainer.setBlockEntityLootTable(level, r, p, BuiltInLootTables.IGLOO_CHEST)"
            )[0],
            "block_entity",
        )
        self.assertEqual(LOOT_CONSTANT.findall("BuiltInLootTables.IGLOO_CHEST"), ["IGLOO_CHEST"])


class StructureContainerBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label)

    def facts(self) -> list:
        return self.store.of_kind("structure_container")

    def payloads(self, structure_type: str) -> list[dict]:
        return [
            fact.payload
            for fact in self.facts()
            if fact.payload["structure_type"] == structure_type
        ]

    def test_facts_carry_provenance(self) -> None:
        self.assertTrue(self.facts(), "结构容器事实为空")
        for fact in self.facts():
            self.assertEqual(fact.prov.input, "src")
            self.assertTrue(fact.prov.file.endswith(".java"), fact.prov.file)

    def test_tables_are_registry_ids(self) -> None:
        for fact in self.facts():
            self.assertTrue(fact.payload["loot_table"].startswith("minecraft:"))

    def test_structures_without_templates_are_covered(self) -> None:
        """下界要塞、要塞、废弃矿井只有代码这一条来源。"""
        covered = {fact.payload["structure_type"] for fact in self.facts()}
        for name in (
            "minecraft:fortress",
            "minecraft:stronghold",
            "minecraft:mineshaft",
        ):
            self.assertIn(name, covered)

    def test_shipwreck_markers_are_paired_with_tables(self) -> None:
        """船骸按 `structure_block` 标记选表，标记名与表的对应只写在 `Map.of` 里。"""
        markers = {
            payload["marker"]: payload["loot_table"]
            for payload in self.payloads("minecraft:shipwreck")
            if payload["container"] == "marker"
        }
        self.assertEqual(markers["supply_chest"], "minecraft:chests/shipwreck_supply")
        self.assertEqual(markers["treasure_chest"], "minecraft:chests/shipwreck_treasure")
        self.assertEqual(markers["map_chest"], "minecraft:chests/shipwreck_map")

    def test_sites_is_a_lower_bound_not_a_count(self) -> None:
        for fact in self.facts():
            self.assertGreaterEqual(fact.payload["sites"], 1)


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class StructureContainer263Test(StructureContainerBase, unittest.TestCase):
    label = "26.3"

    def test_archaeology_processors_are_recorded(self) -> None:
        """海底废墟的可疑方块处理器也挂表，形态是 `processor`。"""
        rows = {p["loot_table"] for p in self.payloads("minecraft:ocean_ruin") if p["container"] == "processor"}
        self.assertEqual(
            rows,
            {"minecraft:archaeology/ocean_ruin_cold", "minecraft:archaeology/ocean_ruin_warm"},
        )

    def test_brushable_block_is_not_a_chest(self) -> None:
        rows = [
            p for p in self.payloads("minecraft:desert_pyramid")
            if p["loot_table"] == "minecraft:archaeology/desert_pyramid"
        ]
        self.assertEqual([p["container"] for p in rows], ["block_entity"])

    def test_monument_has_no_container(self) -> None:
        """海底神殿在本版没有战利品表：数据包无 `chests/monument`，代码也不挂表。

        这条钉住「查不到不等于漏扫」：将来版本加了箱子，它会先在这里报出来。
        """
        self.assertEqual(self.payloads("minecraft:ocean_monument"), [])


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class StructureContainer1182Test(StructureContainerBase, unittest.TestCase):
    label = "1.18.2"

    def test_type_ids_use_this_versions_names(self) -> None:
        """1.18.2 的 id 是 `mansion` / `endcity` / `jungle_pyramid`，不是新版的叫法。"""
        covered = {fact.payload["structure_type"] for fact in self.facts()}
        for name in ("minecraft:mansion", "minecraft:endcity", "minecraft:jungle_pyramid"):
            self.assertIn(name, covered)

    def test_no_archaeology_in_this_version(self) -> None:
        containers = {fact.payload["container"] for fact in self.facts()}
        self.assertNotIn("processor", containers, "1.18.2 还没有考古处理器")


if __name__ == "__main__":
    unittest.main()
