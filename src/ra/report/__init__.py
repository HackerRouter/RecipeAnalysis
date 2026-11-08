"""报告层：把求解结果写成可读、可复算的产物。

产物契约未冻结（下游尚未实现），字段随实现调整。
"""

from __future__ import annotations

from .drift import compare_ledger
from .reachability import (
    ReachabilityReport,
    build_coverage,
    build_reachability,
    build_run_manifest,
    gap_rows,
    write_json,
    write_reachability,
)
from .structure_tables import build_structure_tables

__all__ = [
    "ReachabilityReport",
    "build_coverage",
    "build_reachability",
    "build_run_manifest",
    "build_structure_tables",
    "compare_ledger",
    "gap_rows",
    "write_json",
    "write_reachability",
]
