"""台账跨运行漂移。

「同一路径在两次运行间状态变化 → 报告」。这是最便宜的回归信号：
某文件从 `parsed` 掉成 `classified_skip`，通常说明适配器判据漂了。

三条分支都要覆盖，且不碰真实输出目录：

- 无旧台账 → `baseline`
- 完全一致 → 零漂移
- 状态翻转 / 新增 / 消失 → 报出来
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oa.report.drift import compare_ledger
from oa.facts import FactStore, LedgerStatus


def _make_store(rows: list[tuple[str, LedgerStatus]]) -> FactStore:
    from oa.facts.schema import LedgerRow

    store = FactStore(label="test")
    for file, status in rows:
        store.ledger.add(
            LedgerRow(
                file=file,
                status=status,
                family="test",
                rule="测试规则" if status is LedgerStatus.CLASSIFIED_SKIP else None,
                facts=1 if status is LedgerStatus.PARSED else 0,
                error="测试错误" if status is LedgerStatus.FAILED else None,
            )
        )
    return store


def _write_ledger(directory: Path, rows: list[tuple[str, str]]) -> None:
    lines = [
        json.dumps({"file": file, "status": status, "family": "test"}, ensure_ascii=False)
        for file, status in rows
    ]
    (directory / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


class LedgerDriftTest(unittest.TestCase):
    def test_first_run_is_baseline(self) -> None:
        store = _make_store([("a.json", LedgerStatus.PARSED)])
        with tempfile.TemporaryDirectory() as tmp:
            drift = compare_ledger(Path(tmp), store)
        self.assertTrue(drift["baseline"])
        self.assertEqual(drift["changed"], 0)

    def test_identical_run_has_no_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_ledger(directory, [("a.json", "parsed"), ("b.json", "classified_skip")])
            store = _make_store(
                [
                    ("a.json", LedgerStatus.PARSED),
                    ("b.json", LedgerStatus.CLASSIFIED_SKIP),
                ]
            )
            drift = compare_ledger(directory, store)
        self.assertFalse(drift["baseline"])
        self.assertEqual(drift["changed"], 0)
        self.assertEqual(drift["appeared_count"], 0)
        self.assertEqual(drift["vanished_count"], 0)

    def test_status_flip_is_reported(self) -> None:
        """从 parsed 掉成 classified_skip 是最该被抓到的一类。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_ledger(directory, [("a.json", "parsed")])
            store = _make_store([("a.json", LedgerStatus.CLASSIFIED_SKIP)])
            drift = compare_ledger(directory, store)
        self.assertEqual(drift["changed"], 1)
        self.assertEqual(
            drift["changes"][0],
            {"file": "a.json", "before": "parsed", "after": "classified_skip"},
        )

    def test_new_and_vanished_files_are_reported(self) -> None:
        """状态没变但文件增删也是变化，只盯翻转会漏掉改名与新增目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_ledger(directory, [("old.json", "parsed")])
            store = _make_store([("new.json", LedgerStatus.PARSED)])
            drift = compare_ledger(directory, store)
        self.assertEqual(drift["changed"], 0)
        self.assertEqual(drift["appeared"], ["new.json"])
        self.assertEqual(drift["vanished"], ["old.json"])

    def test_broken_previous_ledger_does_not_crash(self) -> None:
        """上次的台账可能被手改坏；坏行跳过，不整体失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "ledger.jsonl").write_text(
                '{"file": "a.json", "status": "parsed"}\n不是 JSON\n\n',
                encoding="utf-8",
            )
            store = _make_store([("a.json", LedgerStatus.PARSED)])
            drift = compare_ledger(directory, store)
        self.assertEqual(drift["changed"], 0)
        self.assertEqual(drift["vanished_count"], 0)


if __name__ == "__main__":
    unittest.main()
