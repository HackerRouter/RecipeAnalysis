"""集成测试：用真实输入包验证探测与事实化。

只在输入包存在时运行，不下载、不联网。判据是硬事实：
注册表全集、目录归属、方言判定、文件全覆盖。
这些数字是各版本输入包的实测基线，用于防漂移，不是设想值。
变更预期前先跑 `ra probe --label <label>` 确认新值。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ra.paths import repo_root

from tests.support import pack, why

ROOT = repo_root()

# 输入包标签 → 该版本预期。数字是该输入包的实测值，变更前先跑 `ra probe --label <label>` 核对。
EXPECTED = {
    "26.3": {
        "dirs": {"recipe": 2042, "loot_table": 1447, "tags": 883},
        "loot_dialect": "modern",
        "worldgen_source": "datapack",
        "template_dir": "minecraft/structure",
        "components": "components",
    },
    "1.18.2": {
        "dirs": {"recipe": 1058, "loot_table": 986, "tags": 270},
        "loot_dialect": "legacy",
        "worldgen_source": "reports",
        "template_dir": "minecraft/structures",
        "components": "unknown",
    },
}


def _pack(label: str) -> Path | None:
    return pack(label)


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class Probe263Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.support import profile

        cls.pack_dir = _pack("26.3")
        cls.profile = profile("26.3")

    def test_dir_names_detected_by_shape(self) -> None:
        for registry, count in EXPECTED["26.3"]["dirs"].items():
            claim = self.profile.dirs.get(registry)
            self.assertIsNotNone(claim, f"{registry} 未定位")
            self.assertEqual(claim.files, count, f"{registry} 文件数不符基线")
            self.assertGreaterEqual(claim.coverage, 0.5)

    def test_singular_dir_names(self) -> None:
        # 26.3 用单数目录名；探测不得依赖版本号
        self.assertEqual(self.profile.dirs["recipe"].path, "minecraft/recipe")
        self.assertEqual(self.profile.dirs["loot_table"].path, "minecraft/loot_table")

    def test_loot_dialect(self) -> None:
        self.assertEqual(self.profile.loot_dialect, EXPECTED["26.3"]["loot_dialect"])

    def test_worldgen_from_datapack(self) -> None:
        self.assertEqual(self.profile.worldgen_source, "datapack")
        self.assertEqual(sum(self.profile.worldgen_counts.values()), 1144)

    def test_template_dir(self) -> None:
        self.assertEqual(self.profile.template_dir, EXPECTED["26.3"]["template_dir"])

    def test_components_report_present(self) -> None:
        self.assertEqual(self.profile.components_layout, "components")
        self.assertEqual(self.profile.datapack_capability, "ok")

    def test_experimental_pack_excluded(self) -> None:
        self.assertIn("minecraft/datapacks", self.profile.excluded_dirs)

    def test_tag_dirs_anchored(self) -> None:
        item_tag = self.profile.tag_dirs.get("minecraft:item")
        self.assertIsNotNone(item_tag)
        self.assertGreaterEqual(item_tag.coverage, 0.9)
        self.assertEqual(item_tag.files, 236)

    def test_no_unresolved(self) -> None:
        self.assertEqual(self.profile.unresolved, [])


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class Probe1182Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tests.support import profile

        cls.pack_dir = _pack("1.18.2")
        cls.profile = profile("1.18.2")

    def test_plural_dir_names(self) -> None:
        for registry, count in EXPECTED["1.18.2"]["dirs"].items():
            claim = self.profile.dirs.get(registry)
            self.assertIsNotNone(claim, f"{registry} 未定位")
            self.assertEqual(claim.files, count)
        self.assertEqual(self.profile.dirs["recipe"].path, "minecraft/recipes")
        self.assertEqual(self.profile.dirs["loot_table"].path, "minecraft/loot_tables")

    def test_loot_dialect_legacy(self) -> None:
        self.assertEqual(self.profile.loot_dialect, "legacy")

    def test_worldgen_only_in_reports(self) -> None:
        self.assertEqual(self.profile.worldgen_source, "reports")
        self.assertEqual(sum(self.profile.worldgen_counts.values()), 766)

    def test_components_absent(self) -> None:
        self.assertEqual(self.profile.components_layout, "unknown")
        self.assertEqual(self.profile.datapack_capability, "unknown")

    def test_plural_template_dir(self) -> None:
        self.assertEqual(self.profile.template_dir, "minecraft/structures")

    def test_no_unresolved(self) -> None:
        self.assertEqual(self.profile.unresolved, [])


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class IngestCoverageTest(unittest.TestCase):
    """每个输入文件都要有交代，且不得有 failed。"""

    @classmethod
    def setUpClass(cls) -> None:
        from tests.support import audited, pack, profile

        cls.pack_dir = pack("26.3")
        cls.profile = profile("26.3")
        cls.store, cls.unaccounted = audited("26.3")

    def test_every_file_accounted(self) -> None:
        self.assertEqual(self.unaccounted, [])

    def test_no_failed_rows(self) -> None:
        self.assertEqual(self.store.ledger.failed(), [])

    def test_fact_counts_match_baseline(self) -> None:
        counts = self.store.kind_counts()
        self.assertEqual(counts["recipe"], 2042)
        self.assertEqual(counts["loot_table"], 1447)
        self.assertEqual(counts["tag"], 883)
        self.assertEqual(counts["template"], 1511)
        self.assertEqual(counts["worldgen"], 1144)
        self.assertEqual(counts["registry"], 95)
        # 26.3 有默认组件报告与两层交易数据
        self.assertEqual(counts["components"], 1658)
        self.assertEqual(counts["trade"], 391 + 68)
        # 方块变换：数据包 134（130 axe + 3 hoe + 1 shovel）+ 代码侧 1（铜箱）
        self.assertEqual(counts["block_transform"], 135)

    def test_block_transform_axes(self) -> None:
        facts = self.store.of_kind("block_transform")
        by_transformer: dict[str, int] = {}
        for fact in facts:
            name = fact.payload["transformer"]
            by_transformer[name] = by_transformer.get(name, 0) + 1
        self.assertEqual(by_transformer["minecraft:axe"], 130)
        self.assertEqual(by_transformer["minecraft:hoe"], 3)
        self.assertEqual(by_transformer["minecraft:shovel"], 1)
        # 26.3 的变换已基本迁到数据包，代码侧只剩铜箱这类数据包未覆盖的
        registry_side = [
            f for f in facts if f.payload["transformer_kind"] == "registry"
        ]
        code_side = [f for f in facts if f.payload["transformer_kind"] == "code_table"]
        self.assertEqual(len(registry_side), 134)
        self.assertEqual(len(code_side), 1)
        self.assertEqual(code_side[0].payload["to"], "block:minecraft:copper_chest")

    def test_block_transform_environment_is_not_source(self) -> None:
        """`offset` 条件只能是 soft。当成源方块会让「泥土→耕地」指向空气。"""
        facts = self.store.of_kind("block_transform")
        self.assertTrue(facts)
        for fact in facts:
            payload = fact.payload
            for node in payload["from"]:
                self.assertFalse(
                    node.startswith("tag:minecraft:air"),
                    f"空气不得作为源方块：{payload}",
                )
            self.assertEqual(payload["to"].split(":", 1)[0], "block")
            for node in payload["soft"]:
                self.assertIn("=", node, f"soft 应带位置/属性：{node}")

    def test_block_transform_hits_both_kinds_of_rule(self) -> None:
        """两类目标形态（copy_properties 与裸 id）都要覆盖到。"""
        facts = self.store.of_kind("block_transform")
        with_props = [f for f in facts if f.payload["properties"]]
        without_props = [f for f in facts if not f.payload["properties"]]
        self.assertTrue(with_props, "没有任何带属性的变换，copy_properties 可能没解析")
        self.assertTrue(without_props, "没有任何裸 id 变换")

    def test_no_negation_marker_in_this_version(self) -> None:
        # 实测 26.3 用「键缺席」表达不具有，全库 `!` 前缀 0 处
        facts = self.store.of_kind("components")
        self.assertTrue(facts)
        self.assertEqual(sum(len(f.payload["absent"]) for f in facts), 0)

    def test_components_look_sane(self) -> None:
        facts = self.store.of_kind("components")
        by_item = {f.payload["item"]: f.payload for f in facts}
        # 食物有 food 且没有 max_damage；工具反之
        bread = by_item["minecraft:bread"]["components"]
        sword = by_item["minecraft:diamond_sword"]["components"]
        self.assertIn("minecraft:food", bread)
        self.assertNotIn("minecraft:max_damage", bread)
        self.assertIn("minecraft:max_damage", sword)
        self.assertNotIn("minecraft:food", sword)

    def test_trade_layers(self) -> None:
        facts = self.store.of_kind("trade")
        offers = [f for f in facts if f.payload["layer"] == "offer"]
        sets = [f for f in facts if f.payload["layer"] == "set"]
        self.assertEqual(len(offers), 391)
        self.assertEqual(len(sets), 68)
        # 每条交易都要有给与要（否则不可判）
        self.assertTrue(all(f.payload["gives"] and f.payload["wants"] for f in offers))
        # 交易组必须引用标签
        self.assertTrue(all(f.payload["trades_ref"] for f in sets))

    def test_trade_set_references_resolve(self) -> None:
        """交易组引用的标签必须真的存在，否则交易链断了。"""
        trade_tags = {
            f.payload["tag"] for f in self.store.of_kind("tag")
            if f.payload["registry"] == "minecraft:villager_trade"
        }
        self.assertTrue(trade_tags, "交易标签未产出")

        dangling = []
        for fact in self.store.of_kind("trade"):
            if fact.payload["layer"] != "set":
                continue
            ref = fact.payload["trades_ref"]
            if ref and ref.startswith("#") and ref[1:] not in trade_tags:
                dangling.append((fact.payload["set"], ref))
        self.assertEqual(dangling, [], f"交易组引用了不存在的标签：{dangling[:3]}")

    def test_item_universe_comes_from_registry(self) -> None:
        """物品全集只有一条权威来源：`registries.json` 的 `minecraft:item`。

        数据包里没有物品注册表，运行期导出是唯一能给出全集的途径。
        `assets/<ns>/items/` 虽然也逐个列出物品，但服务端 jar 里没有它
        （只有 `lang`），不能当必需输入。
        """
        registry_items = 0
        for fact in self.store.of_kind("registry"):
            if fact.payload["registry"] == "minecraft:item":
                registry_items = len(fact.payload["entries"])
                break
        self.assertEqual(registry_items, 1658)

    def test_assets_accounted(self) -> None:
        """给了 assets/ 就逐文件登记；没给不算缺失。"""
        asset_rows = [r for r in self.store.ledger.rows if r.family == "asset"]
        assets_dir = self.pack_dir / "assets"
        if assets_dir.is_dir():
            self.assertGreater(len(asset_rows), 0, "assets/ 存在但未逐文件登记")
        else:
            self.assertEqual(asset_rows, [], "未提供 assets/，不应凭空产生 asset 行")
        item_rows = [r for r in asset_rows if r.rule == "物品全集的第二条途径"]
        self.assertEqual(len(item_rows), 1658)

    def test_every_fact_has_provenance(self) -> None:
        for fact in self.store.facts:
            self.assertTrue(fact.prov.input)
            self.assertTrue(fact.prov.file)
            self.assertIn(fact.prov.input, ("src", "jar", "pack"))

    def test_partial_facts_explain_themselves(self) -> None:
        for fact in self.store.facts:
            if fact.status.value == "partial":
                self.assertTrue(fact.missing, f"{fact.prov.file} 是 partial 但没说明缺什么")


if __name__ == "__main__":
    unittest.main()
