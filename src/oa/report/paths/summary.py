"""这一版图折叠了什么——终端摘要与 HTML 提示共用一份措辞。

折叠是默认可读性取舍，不是删数据：读者必须知道自己看到的是哪一种视图。
两处各写一份文案会漂（曾经漂过：假设表改名只出现在终端），所以统一从
这里取。预算截断与「走不通」不在这里——它们不是折叠，由调用方单独报。
"""

from __future__ import annotations

from .graph import PathGraph
from .options import PathOptions


def fold_notes(graph: PathGraph, options: PathOptions) -> list[str]:
    """折叠与「没往上展开」的逐条说明。

    顺序固定：标签内的折叠（tag / 条件）→ 假设与起点 → 同构 → 成员层 →
    桶 → 表。与 `graph.py` 里 pass 的执行顺序一致，读者可以照着回溯。
    """
    notes: list[str] = []
    if not options.expand_tags and graph.folded_tags:
        notes.append(f"tag 成员 {graph.folded_tags} 条")
    if not options.expand_conditions and graph.folded_conditions:
        notes.append(
            f"条件 {graph.folded_conditions} 条折叠进标签"
            "（--expand-conditions 展开为节点）"
        )
    if not options.expand_conditions and graph.condition_leaves:
        notes.append(f"条件节点 {graph.condition_leaves} 个（未往上追问）")
    if graph.absorbed_assumptions:
        notes.append(f"假设并入表标签 {graph.absorbed_assumptions} 个")
    if graph.absorbed_roots:
        notes.append(
            f"起点吸进标签 {graph.absorbed_roots} 个节点"
            "（world / assume 不再单独画，--keep-roots 可恢复）"
        )
    if graph.isomorphic_clusters:
        notes.append(
            f"同构簇折叠 {graph.isomorphic_clusters} 簇、{graph.isomorphic} 条规则"
        )
    if graph.absorbed_members:
        notes.append(f"成员层上交 {graph.absorbed_members} 个节点（折叠后不再铺开中间层）")
    if graph.buckets:
        notes.append(f"叶子桶 {graph.buckets} 个")
    if graph.collapsed_tables:
        notes.append(f"压缩战利品表中转节点 {graph.collapsed_tables} 个")
    return notes
