"""结构模板的方块身份来源。

第一手是服务端 jar 内层的二进制模板，经 `--dev` 转成 SNBT 后读。
反编译源码树（`git archive <内容提交> src/main`）里的同名 `.snbt` 是打包副本，
26.3 的 palette 被抹成空串（20791 项全为 `""`）且没有 `DataVersion`，
不是合法的 datagen 输入。参数与转换方向见 `docs/datagen.md`。

三条判据：

- 事实来源必须是 `jar`，`blocks` 非空，`blocks_unreadable` 为假
- `DataVersion` 必须落在事实里
- 反编译源码树的同名文件仍要逐文件登记为 `classified_skip`，不能静默忽略
"""

from __future__ import annotations

import unittest

from oa.adapters.templates import parse_snbt
from oa.inputs.structures import locate_template_dir


def _pack(label: str):
    return pack(label)


def _ingest(label: str):
    from tests.support import store

    return store(label)


def _probe(label: str):
    from tests.support import profile

    return profile(label)


from tests.support import pack, why

class ParseCellTest(unittest.TestCase):
    """两种 cell 形态都要能取到方块实体身份。"""

    def test_legacy_palette_cell(self) -> None:
        text = '{size:[1,1,1],data:[{pos:[0,0,0],state:"minecraft:chest"}],palette:["minecraft:chest"]}'
        doc = parse_snbt(text)
        self.assertEqual(doc["data"][0]["state"], "minecraft:chest")

    def test_packed_cell_with_block_entity(self) -> None:
        text = (
            '{size:[1,1,1],data:[{pos:[0,0,0],state:"minecraft:chest",'
            'nbt:{id:"minecraft:chest",LootTable:"minecraft:chests/x"}}],'
            'palette:["minecraft:chest"]}'
        )
        doc = parse_snbt(text)
        cell = doc["data"][0]
        self.assertEqual(cell["state"], "minecraft:chest")
        self.assertEqual(cell["nbt"]["id"], "minecraft:chest")


class LocateTemplateDirTest(unittest.TestCase):
    """内层 jar 的模板目录靠形状判，不靠目录名单复数。"""

    def test_singular(self) -> None:
        names = [
            "data/minecraft/structure/end_city/base_floor.nbt",
            "data/minecraft/structure/village/plains/house_1.nbt",
            "data/minecraft/loot_table/blocks/stone.json",
        ]
        self.assertEqual(locate_template_dir(names), ("minecraft/structure", 2))

    def test_plural(self) -> None:
        names = [
            "data/minecraft/structures/end_city/base_floor.nbt",
            "data/minecraft/recipes/stone.json",
        ]
        self.assertEqual(locate_template_dir(names), ("minecraft/structures", 1))

    def test_mixed_dir_is_not_a_candidate(self) -> None:
        """既含 .nbt 又含 .json 的目录不是模板目录。"""
        names = [
            "data/minecraft/structure/a.nbt",
            "data/minecraft/structure/a.json",
        ]
        self.assertIsNone(locate_template_dir(names))

    def test_absent(self) -> None:
        self.assertIsNone(locate_template_dir(["data/minecraft/recipe/a.json"]))


class TemplateFactsBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label)
        cls.profile = _probe(cls.label)

    def facts(self) -> list:
        return self.store.of_kind("template")

    def test_has_facts(self) -> None:
        self.assertTrue(self.facts())

    def test_source_is_jar(self) -> None:
        """第一手来源必须是 jar，不是被抹空的反编译源码树副本。"""
        self.assertEqual(self.profile.template_source, "jar")
        self.assertIsNotNone(self.profile.template_root)
        for fact in self.facts():
            self.assertEqual(fact.prov.input, "jar")

    def test_palette_filled_is_recorded(self) -> None:
        """必须记下 palette 有几项有内容，才能判断 blocks 为空是不是来源缺陷。"""
        for fact in self.facts():
            self.assertIn("palette_filled", fact.payload)
            self.assertIn("palette_size", fact.payload)

    def test_data_version_is_recorded(self) -> None:
        """`--dev` 转换会在顶层写 DataVersion；反编译源码树的抹空副本没有它。"""
        for fact in self.facts():
            self.assertIsInstance(fact.payload["data_version"], int)

    def test_blocks_are_readable(self) -> None:
        """模板的普通方块身份必须可得。"""
        for fact in self.facts():
            self.assertGreater(fact.payload["palette_filled"], 0, fact.payload["template"])
            self.assertGreater(fact.payload["block_count"], 0, fact.payload["template"])
            self.assertFalse(fact.payload["blocks_unreadable"], fact.payload["template"])

    def test_no_family_level_limit(self) -> None:
        """来源完整时不该报 `template.blocks` 限制。"""
        families = {item["family"] for item in self.store.unavailable}
        self.assertNotIn("template.blocks", families)

    def test_source_copies_are_ledgered(self) -> None:
        """反编译源码树不再提供数据包，因此没有可登记的模板副本。

        历史实现把反编译源码树的同名 `.snbt` 逐文件登记为「改读 jar」；现在 `data/`
        由 jar 派生且模板不落其中，副本这个类别不复存在。
        """
        rows = [
            row
            for row in self.store.ledger.rows
            if row.family == "template" and row.status.value == "classified_skip"
        ]
        self.assertEqual(rows, [], "数据包已由 jar 派生，不应再有反编译源码副本登记")

    def test_all_templates_come_from_jar(self) -> None:
        """模板的第一手只有 jar：反编译源码树不存数据包。"""
        for fact in self.facts():
            self.assertEqual(fact.prov.input, "jar")

    def test_loot_tables_survive(self) -> None:
        """箱子表不依赖 palette，两版都必须能取到。"""
        with_loot = sum(1 for f in self.facts() if f.payload["loot_tables"])
        self.assertGreater(with_loot, 100, "箱子表数量异常偏少")

    def test_jigsaw_pools_survive(self) -> None:
        with_pools = sum(1 for f in self.facts() if f.payload["jigsaw_pools"])
        self.assertGreater(with_pools, 500)


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class Template263Test(TemplateFactsBase, unittest.TestCase):
    label = "26.3"

    def test_palette_totals(self) -> None:
        """26.3 的 palette 项数固定，钉住以防来源被悄悄换回被抹空的副本。"""
        total = sum(f.payload["palette_size"] or 0 for f in self.facts())
        filled = sum(f.payload["palette_filled"] for f in self.facts())
        self.assertEqual(total, 20791)
        self.assertEqual(filled, 20791)

    def test_data_version_matches_version_json(self) -> None:
        versions = {f.payload["data_version"] for f in self.facts()}
        self.assertEqual(versions, {self.profile.world_version})


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class Template1182Test(TemplateFactsBase, unittest.TestCase):
    label = "1.18.2"

    def test_plural_template_dir(self) -> None:
        self.assertEqual(self.profile.template_dir, "minecraft/structures")

    def test_palette_totals(self) -> None:
        total = sum(f.payload["palette_size"] or 0 for f in self.facts())
        filled = sum(f.payload["palette_filled"] for f in self.facts())
        self.assertEqual(total, 11784)
        self.assertEqual(filled, 11784)


if __name__ == "__main__":
    unittest.main()
