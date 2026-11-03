"""路径图的对外入口：一个物品 id 进，一张可直接看的图出。

两步：`build_path_graph`（内存里的规则 + 求解结果 → `PathGraph`）与
`write_outputs`（`PathGraph` → `.dot` / `.svg` / `.html`），都不读文件；
读 `graph.json` 在 CLI 层。

聚合与减噪为什么放在 `report/` 而不是 `solve/`，见 `docs/development.md`
的分层硬约束。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...ir.nodes import RuleSet, split_node
from ...solve.fixpoint import SolveResult, State
from .graph import Builder, BudgetExceeded, PathGraph
from .noise import (
    absorb_roots,
    bucket_leaves,
    collapse_tables,
    find_isomorphic_clusters,
    merge_isomorphic,
    name_assumption_tables,
)
from .options import PathOptions

__all__ = [
    "PathOptions",
    "PathGraph",
    "PathBuildError",
    "BuiltGraph",
    "build_path_graph",
    "resolve_node",
]


class PathBuildError(Exception):
    """无法为该节点建图（节点不存在、状态不是 TRUE、或图超预算）。"""


@dataclass
class BuiltGraph:
    """建图结果：图本身，加上这一版图做了哪些变换的计数。"""

    graph: PathGraph
    value: str
    state: State
    truncated_at: str | None = None
    isomorphic_clusters: int = 0
    collapsed_tables: int = 0
    absorbed_assumptions: int = 0
    absorbed_roots: int = 0


def resolve_node(token: str, sorts: frozenset[str] | set[str]) -> str:
    """把用户输入变成节点 id。

    接受三种写法：完整节点（`item:minecraft:cod_bucket`）、裸 id
    （`minecraft:cod_bucket`）、裸名（`cod_bucket`）。后两种补成 `item:`——
    其余排序（block / entity / table）不猜，猜错会静默给出另一件东西的图。
    """
    head, sep, _ = token.partition(":")
    if sep and head in sorts:
        return token
    if sep:
        return f"item:{token}"
    return f"item:minecraft:{token}"


def build_path_graph(
    rule_set: RuleSet,
    result: SolveResult,
    value: str,
    options: PathOptions,
) -> BuiltGraph:
    """按参数把 `value` 的来源展开成一张图。

    只画 body 全为 `TRUE` 的规则——图上每条边都能一路追到 `assume:` / `world:`。
    走不通的途径不画边，但按 `Builder._blocked` 的规则报数，不静默丢弃。
    """
    try:
        sort = split_node(value)[0]
    except ValueError as exc:
        raise PathBuildError(f"节点 id 不合法：{value}（{exc}）") from exc
    if sort == "":  # pragma: no cover - split_node 已挡
        raise PathBuildError(f"节点 id 不合法：{value}")

    if not rule_set.of_head(value) and result.of(value) is not State.TRUE:
        raise PathBuildError(
            f"{value} 状态为 {result.of(value).value}，没有可画的来源"
        )

    by_head = {head: rule_set.of_head(head) for head in rule_set.heads()}
    builder = Builder(
        by_head,
        result,
        max_depth=options.depth,
        max_branches=options.branches,
        max_nodes=options.max_nodes,
        max_groups=options.max_groups,
        group_min=options.group_min,
        expand_tags=options.expand_tags,
        expand_conditions=options.expand_conditions,
        expand_groups=options.expand_groups,
    )

    truncated: str | None = None
    try:
        builder.visit(value, 0, frozenset({value}))
    except BudgetExceeded as exc:
        # 截断不是错误：图已经可用，只是少了分支。留痕后继续。
        truncated = str(exc)

    graph = builder.graph
    clusters = find_isomorphic_clusters(by_head, result, min_size=options.merge_isomorphic)
    graph.isomorphic_clusters = merge_isomorphic(graph, clusters, by_head)
    # 顺序不能反：`collapse_tables` 靠「表有唯一入边」判可压，而
    # `name_assumption_tables` 会把 `assume → table` 那条入边删掉。先命名
    # 后压缩，所有假设表都变成「零入边」而被跳过，表节点全留在图上。
    graph.collapsed_tables = 0 if options.keep_tables else collapse_tables(graph)
    name_assumption_tables(graph)
    # 起点吸收放在最后一道链收缩之后：`collapse_tables` 会把
    # `world → block → table → item` 缩成更短的形式，起点可能因此变成唯一入边。
    absorb_roots(graph, keep=options.keep_roots)
    bucket_leaves(graph, options.merge_leaves)
    # 目标要在所有收缩之后记录：中间那几道 pass 可能删掉节点、也可能把
    # 别的节点顶到目标的位置（`collapse_tables` 会把表压进边），但目标本身
    # 从不会被删——它是 `visit` 的起点。这里记下来，渲染时据此高亮。
    graph.target = value

    # 变换计数以 `PathGraph` 为准：终端摘要与 HTML 提示都从图上读同一份，
    # 这里只是转发，不另存状态。
    return BuiltGraph(
        graph=graph,
        value=value,
        state=result.of(value),
        truncated_at=truncated,
        isomorphic_clusters=graph.isomorphic_clusters,
        collapsed_tables=graph.collapsed_tables,
        absorbed_assumptions=graph.absorbed_assumptions,
        absorbed_roots=graph.absorbed_roots,
    )
