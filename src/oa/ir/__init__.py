"""阶段二：事实 → 规则。

只有一种形状 `head ← body`，OR 由多条同 head 规则表达。
来源族的差异只影响 `families/` 与 `bridges/`，求解器不感知。
"""

from __future__ import annotations

from .compile import IR_SCHEMA, CompileReport, KnowledgeError, compile_ir
from .nodes import LINK_KINDS, SORTS, NodeError, Rule, RuleSet, node, split_node

__all__ = [
    "IR_SCHEMA",
    "LINK_KINDS",
    "SORTS",
    "CompileReport",
    "KnowledgeError",
    "NodeError",
    "Rule",
    "RuleSet",
    "compile_ir",
    "node",
    "split_node",
]
