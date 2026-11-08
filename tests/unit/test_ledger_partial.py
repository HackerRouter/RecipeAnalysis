"""台账的 partial 状态。

事实有三态，台账必须能区分「完整产出」与「有产出但缺项」：只记 `parsed`
会把缺项掩盖成完整，只记 `failed` 会把仍在用的文件说成没产出。
"""

from __future__ import annotations

import unittest

from ra.adapters.base import record
from ra.facts import FactStore, LedgerStatus
from ra.facts.schema import Coverage, LedgerRow


class LedgerPartialTest(unittest.TestCase):
    def test_partial_requires_missing(self) -> None:
        with self.assertRaises(ValueError):
            LedgerRow(file="a.json", status=LedgerStatus.PARTIAL)

    def test_record_infers_partial(self) -> None:
        store = FactStore(label="test")
        record(store, "a.json", "trade", facts=1, missing=("wants 无法解析",))
        row = store.ledger.rows[0]
        self.assertIs(row.status, LedgerStatus.PARTIAL)
        self.assertEqual(row.missing, ("wants 无法解析",))

    def test_record_without_missing_is_parsed(self) -> None:
        store = FactStore(label="test")
        record(store, "a.json", "trade", facts=1)
        self.assertIs(store.ledger.rows[0].status, LedgerStatus.PARSED)

    def test_json_carries_missing(self) -> None:
        row = LedgerRow(
            file="a.json",
            status=LedgerStatus.PARTIAL,
            family="trade",
            facts=1,
            missing=("gives 无法解析",),
        )
        self.assertEqual(row.as_json()["missing"], ["gives 无法解析"])

    def test_coverage_counts_partial_as_produced(self) -> None:
        store = FactStore(label="test")
        record(store, "a.json", "trade", facts=1)
        record(store, "b.json", "trade", facts=1, missing=("缺项",))
        coverage = store.coverage()[0]
        self.assertEqual(coverage.parsed, 1)
        self.assertEqual(coverage.partial, 1)
        self.assertEqual(coverage.ratio, 1.0)


if __name__ == "__main__":
    unittest.main()
