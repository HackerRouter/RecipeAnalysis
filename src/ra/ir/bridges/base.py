"""桥接的公共产物容器。

各桥接函数只往这里攒规则与统计，不彼此调用。
"""

from __future__ import annotations

from ..nodes import Rule

__all__ = ["BridgeResult"]


class BridgeResult:
    def __init__(self) -> None:
        self.rules: list[Rule] = []
        self.stats: dict[str, int] = {}
        self.notes: list[str] = []
        self.missing_stations: list[str] = []
        self.convention_checked = 0
        self.convention_matched = 0
