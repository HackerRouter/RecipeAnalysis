"""阶段三：获取路径推理。

三值最小不动点 + 证明 + 归因。求解器零知识——
它只知道 `head ← body` 与初始播种，不知道什么是熔炉。
"""

from __future__ import annotations

from .attribute import (
    BLOCKED,
    CYCLE,
    NO_RULE,
    UNDETERMINED,
    UNOBTAINABLE,
    Attribution,
    Graph,
    attribute,
)
from .fixpoint import SolveResult, State, solve
from .proof import Step, enumerate_proofs, flatten_leaves, iter_steps
from .scc import component_members, strongly_connected

__all__ = [
    "BLOCKED",
    "CYCLE",
    "NO_RULE",
    "UNDETERMINED",
    "UNOBTAINABLE",
    "Attribution",
    "Graph",
    "SolveResult",
    "State",
    "Step",
    "attribute",
    "component_members",
    "enumerate_proofs",
    "flatten_leaves",
    "iter_steps",
    "solve",
    "strongly_connected",
]
