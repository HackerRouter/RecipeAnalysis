"""战利品条目的权重与分组在事实里必须留得住。

事实只做语法还原，但**摊平不等于丢语义**：只留 `children` 计数时，
「二选一」与「两个都给」在产物上长得一样，权重更是直接消失——
下游算「一个箱子平均给多少」全依赖这两项。

判据见 [`docs/shapes.md`](../../docs/shapes.md) 的「战利品表」一节。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ra.paths import pack_data

from tests.support import pack, profile, why


def _pack(label: str):
    return pack(label)


def _store(label: str):
    from tests.support import store

    return store(label)


def _raw_weighted_entries(label: str) -> int:
    """直接从原始数据包数「带 weight 的条目」，作为事实侧的对账基准。

    只走 `pools[].entries[].children[]`：`weight` 在函数参数（如随机数量、
    可疑炖菜的效果列表）里也会出现，那些不是条目，算进来会虚高。
    """

    def count(entries: object) -> int:
        if not isinstance(entries, list):
            return 0
        total = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            total += 1 if "weight" in entry else 0
            total += count(entry.get("children"))
        return total

    # 只扫适配器声明的目录：`data/minecraft/datapacks/` 下还嵌着别的数据包，
    # 它们不在本次输入范围内，一起数会虚高。
    claim = profile(label).dirs["loot_table"]
    namespace, _, relative = claim.path.partition("/")
    root = pack_data(pack(label)) / namespace / relative
    found = 0
    for path in sorted(root.rglob("*.json")):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        for pool in doc.get("pools") or []:
            if isinstance(pool, dict):
                found += count(pool.get("entries"))
    return found


class LootEntryBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _store(cls.label)

    def entries(self) -> list[dict]:
        return [
            entry
            for fact in self.store.of_kind("loot_table")
            for pool in fact.payload["pools"]
            for entry in pool["entries"]
        ]

    def test_weight_count_matches_the_pack(self) -> None:
        weighted = [entry for entry in self.entries() if "weight" in entry]
        self.assertEqual(len(weighted), _raw_weighted_entries(self.label))

    def test_grouped_entries_are_labelled(self) -> None:
        """`children > 0` 的条目要带自己的分组身份，子条目要带所在分组。"""
        containers = [entry for entry in self.entries() if entry["children"] > 0]
        self.assertTrue(containers)
        for entry in containers:
            self.assertIn("group_id", entry, entry["kind"])
            self.assertEqual(entry["group_kind"], entry["kind"])
        children = [
            entry
            for entry in self.entries()
            if "group_id" in entry and entry["children"] == 0
        ]
        self.assertTrue(children)
        for entry in children:
            self.assertIn(entry["group_kind"], {"alternatives", "sequence", "group"})

    def test_group_references_resolve(self) -> None:
        """子条目指向的分组 id 必须在同一张表里存在。"""
        for fact in self.store.of_kind("loot_table"):
            pools = fact.payload["pools"]
            groups = {
                entry["group_id"]
                for pool in pools
                for entry in pool["entries"]
                if entry["children"] > 0
            }
            for pool in pools:
                for entry in pool["entries"]:
                    group = entry.get("group_id")
                    if group is None or entry["children"] > 0:
                        continue
                    self.assertIn(group, groups, fact.payload["table"])

    def test_no_failed_rows(self) -> None:
        self.assertEqual(self.store.ledger.failed(), [])


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class LootEntry263Test(LootEntryBase, unittest.TestCase):
    label = "26.3"

    def test_weighted_entry_count(self) -> None:
        """验收项：26.3 带 `weight` 的条目数为 645。"""
        self.assertEqual(
            sum(1 for entry in self.entries() if "weight" in entry),
            645,
        )


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class LootEntry1182Test(LootEntryBase, unittest.TestCase):
    label = "1.18.2"


if __name__ == "__main__":
    unittest.main()
