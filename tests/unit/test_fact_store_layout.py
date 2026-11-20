"""事实目录的落盘布局。

`output/<label>/facts/` 是事实库的唯一入口：事实（`<种类>.jsonl`）、台账
（`ledger.jsonl`）与汇总（`summary.json`）同处一层。下游按事实种类取文件，
所以台账不能当事实读；读回时三者都要能各自就位。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra.facts import FactStore, LedgerStatus
from ra.facts.schema import Fact, LedgerRow, Prov, Status


def _store() -> FactStore:
    store = FactStore(label="test")
    store.add(
        Fact(
            kind="registry",
            payload={"registry": "minecraft:item", "entries": ["minecraft:stone"]},
            prov=Prov(input="jar", file="reports/registries.json"),
        )
    )
    store.add(
        Fact(
            kind="recipe",
            payload={"id": "minecraft:x", "result": {}},
            prov=Prov(input="pack", file="data/minecraft/recipe/x.json"),
        )
    )
    store.ledger.add(
        LedgerRow(file="data/minecraft/recipe/x.json", status=LedgerStatus.PARSED, family="recipe")
    )
    store.mark_unavailable("components", "no_report", note="该版本没有默认组件报告")
    store.extra["ledger_drift"] = {"baseline": True}
    return store


class FactStoreLayoutTest(unittest.TestCase):
    def test_write_puts_ledger_and_summary_in_facts_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            facts_dir = Path(tmp) / "facts"
            paths = _store().write(facts_dir)

            self.assertEqual(paths["ledger"], facts_dir / "ledger.jsonl")
            self.assertEqual(paths["summary"], facts_dir / "summary.json")
            self.assertEqual(paths["registry"], facts_dir / "registry.jsonl")
            self.assertTrue((facts_dir / "summary.json").is_file())

    def test_read_skips_ledger_and_keeps_summary_extra(self) -> None:
        """台账没有 `kind`，被当事实读会直接崩；它要按文件名分开处理。"""
        with tempfile.TemporaryDirectory() as tmp:
            facts_dir = Path(tmp) / "facts"
            _store().write(facts_dir)
            self.assertTrue((facts_dir / "ledger.jsonl").is_file())
            store = FactStore.read(facts_dir, label="test")

        self.assertEqual(store.kind_counts(), {"recipe": 1, "registry": 1})
        self.assertEqual(store.status_counts(), {"parsed": 2, "partial": 0, "failed": 0})
        self.assertEqual(store.ledger.counts(), {"parsed": 1})
        self.assertEqual(store.unavailable[0]["family"], "components")
        self.assertTrue(store.extra["ledger_drift"]["baseline"])

    def test_partial_missing_survives_round_trip(self) -> None:
        """`partial` 必须带 `missing`；读回后两者都要在。"""
        store = FactStore(label="test")
        store.add(
            Fact(
                kind="tag",
                payload={"id": "minecraft:planks", "entries": []},
                prov=Prov(input="pack", file="data/minecraft/tags/item/planks.json"),
                status=Status.PARTIAL,
                missing=("entries",),
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            facts_dir = Path(tmp) / "facts"
            store.write(facts_dir)
            read = FactStore.read(facts_dir)

        self.assertEqual(read.status_counts(), {"parsed": 0, "partial": 1, "failed": 0})
        self.assertEqual(read.of_kind("tag")[0].missing, ("entries",))


if __name__ == "__main__":
    unittest.main()
