"""idiom 命中数的三档语义，与台账说明行的键稳定性。

两处都是「产物看起来对、语义已经错」的隐患：

1. `min_hits` 曾当硬下限用，把「机制搬到数据包后代码侧只剩 1 条」报成族不可用。
   26.3 的方块变换正是这种情况，误报会让读者以为抽取坏了。
2. 台账说明行曾用 `len(store.ledger.rows)` 做键，键随插入位置变化。
   把 365 条说明聚合成 1 条后，旧键全消失，漂移报告凭空多出 366 条「文件消失」。
"""

from __future__ import annotations

import unittest

from ra.adapters.source import _fold_notes


def _pack(label: str):
    return pack(label)


def _ingest(label: str):
    from tests.support import store

    return store(label)


from tests.support import pack, why

class FoldNotesTest(unittest.TestCase):
    def test_short_list_kept_verbatim(self) -> None:
        notes = ["a", "b", "c"]
        self.assertEqual(_fold_notes(notes), "a ；b ；c")

    def test_long_list_is_collapsed_but_head_kept(self) -> None:
        """折叠不能丢线索：前几条原文要留，否则「哪些文件没解析」就查不到了。"""
        notes = [f"note{i}" for i in range(20)]
        folded = _fold_notes(notes)
        self.assertIn("note0", folded)
        self.assertIn("另有同类说明 12 条", folded)
        self.assertLess(len(folded), len(" ；".join(notes)))

    def test_empty_is_empty(self) -> None:
        self.assertEqual(_fold_notes([]), "")


class IdiomYieldSemanticsBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label)

    def unavailable_families(self) -> set[str]:
        return {item["family"] for item in self.store.unavailable}

    def low_yield(self) -> list[dict]:
        return self.store.extra.get("low_yield_idioms", [])

    def test_zero_hit_idioms_are_unavailable_not_low_yield(self) -> None:
        """命中 0 与「低于下限但非零」必须是两种语义。"""
        zero = {
            item["family"] for item in self.store.unavailable
            if item["family"].startswith("idiom:")
        }
        low = {item["idiom"] for item in self.low_yield()}
        self.assertEqual(zero & {f"idiom:{name}" for name in low}, set())

    def test_notes_are_folded_into_one_row_per_idiom(self) -> None:
        """每个 idiom 至多一行说明，键固定。"""
        counts: dict[str, int] = {}
        for row in self.store.ledger.rows:
            if row.rule and row.rule.startswith("idiom ") and row.rule.endswith(" 说明"):
                counts[row.rule] = counts.get(row.rule, 0) + 1
        over = {rule: n for rule, n in counts.items() if n > 1}
        self.assertEqual(over, {}, "同一 idiom 出现多行说明，键不稳定")

    def test_note_keys_have_no_running_index(self) -> None:
        """键里不能带随插入位置变化的序号，否则漂移报告会误报文件消失。"""
        for row in self.store.ledger.rows:
            if "<idiom:" in row.file:
                tail = row.file.rsplit(">", 1)
                self.assertEqual(
                    tail[-1], "",
                    f"说明行键带了后缀 {tail[-1]!r}，会让跨运行比对失真：{row.file}",
                )


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class IdiomYield263Test(IdiomYieldSemanticsBase, unittest.TestCase):
    label = "26.3"

    def test_transform_tables_is_low_yield_not_unavailable(self) -> None:
        """26.3 的方块变换迁到了数据包，代码侧只剩铜箱 1 条——这是搬家，不是坏了。"""
        names = {item["idiom"] for item in self.low_yield()}
        self.assertIn("block_transform_tables", names)
        self.assertNotIn(
            "idiom:block_transform_tables", self.unavailable_families(),
            "机制搬家不该报成族不可用",
        )

    def test_villager_trades_is_unavailable(self) -> None:
        """26.3 的交易整族搬到数据包，代码侧真的 0 条。"""
        self.assertIn("idiom:villager_trades", self.unavailable_families())


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class IdiomYield1182Test(IdiomYieldSemanticsBase, unittest.TestCase):
    label = "1.18.2"

    def test_no_low_yield(self) -> None:
        """1.18.2 各 idiom 都达到参考下限。"""
        self.assertEqual(self.low_yield(), [])


if __name__ == "__main__":
    unittest.main()
