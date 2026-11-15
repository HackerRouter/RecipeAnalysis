"""袭击波次表的提取。

判据：

- 枚举顺序与数组下标对齐波次（第 0 位在代码里不被读取）
- 0 也要产事实：它表示「这一波不刷它」
- 规则形状是 `entity ←spawns← assume:raid`，波次与数量进 meta
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ra.adapters.source.idioms.raid_waves import RaidWaves
from ra.adapters.source.index import JavaFile, JavaIndex

RAID_JAVA = """
public class Raid implements RaidAccessor {
    private static enum RaiderType {
        VINDICATOR(EntityTypes.VINDICATOR, new int[]{0, 0, 2, 0, 1, 4, 2, 5}),
        EVOKER(EntityTypes.EVOKER, new int[]{0, 0, 0, 0, 0, 1, 1, 2}),
        PILLAGER(EntityTypes.PILLAGER, new int[]{0, 4, 3, 3, 4, 4, 4, 2}),
        WITCH(EntityTypes.WITCH, new int[]{0, 0, 0, 0, 3, 0, 0, 1}),
        RAVAGER(EntityTypes.RAVAGER, new int[]{0, 0, 0, 1, 0, 1, 0, 2});
    }
}
"""

RAID_JAVA_LEGACY = """
public class Raid {
    static enum RaiderType {
        PILLAGER(EntityType.PILLAGER, new int[]{0, 4, 3});
    }
}
"""


def _index(text: str) -> JavaIndex:
    index = JavaIndex(label="synthetic", root=Path("/nonexistent"))
    path = "net/minecraft/world/entity/raid/Raid.java"
    index.files[path] = JavaFile(path=path, text=text, anchors=())
    return index


def _links(text: str) -> list[dict]:
    return [fact.payload["link"] for fact in RaidWaves().run(_index(text)).links]


def _metas(text: str) -> list[dict]:
    return [fact.payload["meta"] for fact in RaidWaves().run(_index(text)).links]


class RaidWaveTest(unittest.TestCase):
    def test_wave_index_matches_array(self) -> None:
        """第 1 波是数组下标 1，不是 0。"""
        facts = RaidWaves().run(_index(RAID_JAVA)).links
        by_key = {
            (fact.payload["link"]["head"], fact.payload["meta"]["wave"]): fact.payload["meta"]["count"]
            for fact in facts
        }
        # PILLAGER: 下标 1..7 → 4,3,3,4,4,4,2
        self.assertEqual(by_key[("entity:minecraft:pillager", 1)], 4)
        self.assertEqual(by_key[("entity:minecraft:pillager", 2)], 3)
        self.assertEqual(by_key[("entity:minecraft:pillager", 7)], 2)
        # VINDICATOR 前两波不刷
        self.assertEqual(by_key[("entity:minecraft:vindicator", 1)], 0)

    def test_zero_is_kept(self) -> None:
        """「这一波不刷它」也是信息，丢掉会让下游无法区分 0 只与无此实体。"""
        metas = [m for m in _metas(RAID_JAVA) if m["wave"] == 1]
        self.assertEqual(len(metas), 5, "第 1 波五个实体各一条")
        self.assertEqual([m["count"] for m in metas].count(0), 4)

    def test_all_five_entities_six_ways(self) -> None:
        heads = {link["head"] for link in _links(RAID_JAVA)}
        self.assertEqual(
            heads,
            {
                "entity:minecraft:vindicator",
                "entity:minecraft:evoker",
                "entity:minecraft:pillager",
                "entity:minecraft:witch",
                "entity:minecraft:ravager",
            },
        )

    def test_link_shape(self) -> None:
        link = _links(RAID_JAVA)[0]
        self.assertEqual(link["kind"], "spawns")
        self.assertEqual(link["via"], ["assume:raid"])

    def test_legacy_entity_type_prefix(self) -> None:
        links = _links(RAID_JAVA_LEGACY)
        self.assertEqual(len(links), 2, "下标 1 与 2，跳过 0")
        self.assertEqual(links[0]["head"], "entity:minecraft:pillager")
        self.assertEqual([m["count"] for m in _metas(RAID_JAVA_LEGACY)], [4, 3])

    def test_missing_raid_file_is_reported(self) -> None:
        index = JavaIndex(label="synthetic", root=Path("/nonexistent"))
        result = RaidWaves().run(index)
        self.assertEqual(result.links, [])
        self.assertTrue(any("Raid.java" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
