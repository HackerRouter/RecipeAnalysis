"""台账漂移检测：与上一次运行的台账比对，报出状态变化的文件。

判据：同一路径在两次运行间状态变化 → 报告。这是最便宜的回归信号——
某个文件从 `parsed` 变成 `classified_skip`，通常意味着适配器的判据漂了，
比等下游报告「这个物品不可达」要早得多。

首次运行（无旧台账）返回 `{"baseline": True}`，不算漂移。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..facts.store import LEDGER_FILE

__all__ = ["compare_ledger"]

# 每类变化最多保留的明细条数。台账动辄上千行，全量塞进 summary 没有意义，
# 只要够看出「变了什么类型」即可。
KEEP = 50


def _read_statuses(path: Path) -> dict[str, str]:
    """旧台账 → `{file: status}`。读不动就当作没有旧台账，不报错。"""
    if not path.is_file():
        return {}
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = row.get("status")
        if isinstance(row.get("file"), str) and isinstance(status, str):
            rows[row["file"]] = status
    return rows


def compare_ledger(facts_dir: Path, store) -> dict:
    """比对本次台账与事实目录里已有的 `ledger.jsonl`。

    返回的字典直接进 `store.extra["ledger_drift"]`，由 CLI 打印摘要。
    状态翻转与「新出现 / 消失」分开报：前者是判据变了，后者是输入变了，
    处理方式不同。
    """
    before = _read_statuses(facts_dir / LEDGER_FILE)
    if not before:
        return {"baseline": True, "changed": 0}

    changes = store.ledger.diff_against(before)
    current = {row.file for row in store.ledger.rows}
    appeared = sorted(current - set(before))
    vanished = sorted(set(before) - current)
    return {
        "baseline": False,
        "changed": len(changes),
        "changes": changes[:KEEP],
        "appeared": appeared[:KEEP],
        "appeared_count": len(appeared),
        "vanished": vanished[:KEEP],
        "vanished_count": len(vanished),
    }
