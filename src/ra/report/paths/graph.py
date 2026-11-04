"""规则 → 有向图（`PathGraph`），以及按预算遍历的 `Builder`。

## 图的基本形状

| 语义 | 画法 |
|---|---|
| AND（一条规则的全部前置） | 所有前置汇进同一个菱形 |
| OR（同一产物有多条规则） | 多个菱形指向同一个产物 |
| 链路方向 | 一律「来源 → 产物」，从下往上读是获取路径 |

单前件、无条件的规则不画菱形，直接压成边；环边画成灰色虚线。

减噪里有两层在遍历时顺手完成（tag 不展开、同类来源聚成 folder），其余
pass 在 `noise.py`。判据与取舍见
`docs/adr/0020-graph-representation-and-rendering.md`。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ...ir.nodes import Rule, split_node
from ...solve.fixpoint import SolveResult, State
from .style import (
    CONDITION_COLOR,
    DROP_KINDS,
    ROOT_SORTS,
    category_of,
    condition_label,
    edge_label,
    is_condition,
    kind_style,
    rule_label,
    short,
    short_template,
    stacked,
    sub_key,
)


class BudgetExceeded(Exception):
    """节点数超过 `max_nodes`。截断，不静默继续。"""


@dataclass
class PathGraph:
    """一张待渲染的图。只存显示需要的东西，不保留规则对象。"""

    nodes: dict[str, dict] = field(default_factory=dict)
    # (source, target, tag) -> (label, tooltip)。
    #
    # 一对端点可以有多条边：同一个物品可能被两张不同的战利品表掉出，
    # 同一个方块可能被两个不同结构生成。合成一条边会把两种来源挤进一个
    # 用 `/` 拼的标签里，读不出来是谁给的。
    edges: dict[tuple[str, str, str], tuple[str, str]] = field(default_factory=dict)
    # 边色按「这条边属于哪条规则 / 哪个组」着色
    edge_colors: dict[tuple[str, str, str], str] = field(default_factory=dict)
    # 虚线边：表示「附加信息」而非前提（如模板出处）
    dashed: set[tuple[str, str, str]] = field(default_factory=set)
    # 条件边：设备 / 工具 / 附魔。它们是 AND 的一员（保留箭头），
    # 但用虚线与独立颜色，免得与「东西从哪来」混为一谈。
    condition_edges: set[tuple[str, str, str]] = field(default_factory=set)
    # 被预算截掉的节点 → 未展开的规则数
    omitted: dict[str, int] = field(default_factory=dict)
    # 因 body 里有 FALSE / UNKNOWN 而未画的节点 → 走不通的规则数。
    # 与 `omitted` 分开：截断是「看得见但没铺开」，这里是「这条途径根本走不通」，
    # 两者的补法不同（前者加预算，后者补事实）。
    blocked: dict[str, int] = field(default_factory=dict)
    rules: set[str] = field(default_factory=set)
    # 单前件规则：不画菱形，直接压成边
    merged: set[str] = field(default_factory=set)
    # 聚合组 → 覆盖的规则数
    groups: dict[str, int] = field(default_factory=dict)
    # 折叠掉的 tag 成员数、停在叶子的条件数，用于统计输出
    folded_tags: int = 0
    condition_leaves: int = 0
    # 折叠进菱形标签的条件条数
    folded_conditions: int = 0
    # 被吸收进表节点标签的假设数
    absorbed_assumptions: int = 0
    # 起点被吸进标签的产物数
    absorbed_roots: int = 0
    # 被折叠进同构聚合边的产物数
    isomorphic: int = 0
    # 被上交到聚合 tag 的成员层节点数
    absorbed_members: int = 0
    # 叶子桶数（与 `groups` 分开：桶是「同类来源 N 条」，组是「同类规则 N 条」）
    buckets: int = 0
    # 折成聚合边的同构簇数（`isomorphic` 记的是这些簇压掉多少条规则）
    isomorphic_clusters: int = 0
    # 压进边的 `table:` 中转节点数
    collapsed_tables: int = 0
    # 聚合组内部的规则全部来自全局起点时，folder 本身没有入边；
    # 这里记下「这个产物是由起点生成的」，供 `absorb_roots` 写进标签。
    # 值形如 {产物: [(起点, 边标签)]}。
    pending_roots: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    # 被预算（`--branches`）挡住、本该进图却没进的节点。
    #
    # `merge_isomorphic` 的「多数成员在图里」判据需要它：默认 `--branches 4`
    # 会把 13 种木台阶只铺开 4 种，不把剩下 9 种算进来，同构簇永远折不动——
    # 两个减噪参数互相压制，用户开了 `--merge-isomorphic` 也只当没开。
    suppressed: set[str] = field(default_factory=set)
    # 这张图是为哪个节点画的。渲染时高亮它——一眼看出「其余都是它的来源」。
    #
    # 存成字段而不是渲染参数：图的主题是图的一部分，`build_dot` / `render_html`
    # 都该读同一处。传参会让两者可能不一致（HTML 标题写 A、图上高亮 B）。
    target: str = ""

    def edge_dropped(self, key: tuple[str, str, str]) -> None:
        """删一条边，同时清掉它在三个旁路集合里的登记。

        三处分开记（颜色、虚线、条件）是为了渲染时不必回查规则；
        删边时漏清一处，会留下指向已删端点的颜色/样式记录。
        """
        self.edges.pop(key, None)
        self.edge_colors.pop(key, None)
        self.dashed.discard(key)
        self.condition_edges.discard(key)

    def forget_nodes(self, nodes: set[str] | list[str]) -> None:
        """删节点与它们的所有边。"""
        doomed = set(nodes)
        for key in [k for k in self.edges if k[0] in doomed or k[1] in doomed]:
            self.edge_dropped(key)
        for node in doomed:
            self.nodes.pop(node, None)
            self.omitted.pop(node, None)
            self.blocked.pop(node, None)
            self.groups.pop(node, None)
        self.rules = {r for r in self.rules if f"rule::{r}" in self.nodes}


class Builder:
    """按预算遍历规则，把每一步登记成节点与边。"""

    def __init__(
        self,
        rules_by_head: dict[str, list[Rule]],
        result: SolveResult,
        *,
        max_depth: int,
        max_branches: int,
        max_nodes: int,
        max_groups: int,
        group_min: int,
        expand_tags: bool,
        expand_conditions: bool,
        expand_groups: bool,
    ) -> None:
        self.rules_by_head = rules_by_head
        self.result = result
        self.max_depth = max_depth
        # <= 0 表示全部展开，只受 max_nodes 约束
        self.max_branches = max_branches
        self.max_nodes = max_nodes
        self.max_groups = max_groups
        self.group_min = group_min
        self.expand_tags = expand_tags
        self.expand_conditions = expand_conditions
        self.expand_groups = expand_groups
        self.graph = PathGraph()

    # ---- 节点登记 ----

    def _value(self, value: str, **attrs) -> None:
        try:
            sort = split_node(value)[0]
        except ValueError:
            sort = "item"
        info = self.graph.nodes.setdefault(value, {"sort": sort})
        info.update({k: v for k, v in attrs.items() if v})
        if len(self.graph.nodes) > self.max_nodes:
            raise BudgetExceeded(value)

    def _rule(self, rule: Rule) -> str:
        key = f"rule::{rule.id}"
        if key not in self.graph.nodes:
            self.graph.nodes[key] = {
                "sort": "rule",
                "label": rule_label(rule, inline_conditions=not self.expand_conditions),
                "tooltip": rule.id,
                # 桶化要按「这条规则属于哪类来源」取名。同一 family 下类别可能不同
                # （`trades` 里流浪商人与职业村民并列），只能由规则自己给出。
                "category": category_of(rule)[1],
            }
            self.graph.rules.add(rule.id)
            if len(self.graph.nodes) > self.max_nodes:
                raise BudgetExceeded(key)
        return key

    def _group(self, head: str, rules: list[Rule]) -> str:
        """一组同类来源 → 一个组节点。"""
        key = f"group::{head}::{category_of(rules[0])[0]}"
        if key in self.graph.nodes:
            return key
        name = category_of(rules[0])[1]
        subs = Counter(sub_key(r) for r in rules)
        label = f"{name} · {len(rules)} 条"
        if 1 < len(subs) <= 6:
            # 一行一个：`、` 串起来的 3 个结构名能占 60 字符宽，folder 就被
            # 拉成一条细横条，而高度本来免费（同层节点按最高者对齐）。
            # 省略号也另起一行：接在名字后面会被读成名字的一部分
            # （`stronghold_library…`）。
            listed = list(subs)[:3]
            label += "\\n" + stacked(listed)
            if len(subs) > 3:
                label += "\\n…"
        elif len(subs) > 6:
            label += f"\\n{len(subs)} 种"
        detail = "\n".join(f"{r.id}" for r in rules[:15])
        if len(rules) > 15:
            detail += f"\n…另有 {len(rules) - 15} 条"
        self.graph.nodes[key] = {
            "sort": "group",
            "label": label,
            "tooltip": f"{name}（{len(rules)} 条 · {len(subs)} 种）\n{detail}",
        }
        self.graph.groups[key] = len(rules)
        if len(self.graph.nodes) > self.max_nodes:
            raise BudgetExceeded(key)
        return key

    def _edge(
        self,
        source: str,
        target: str,
        label: str,
        tooltip: str,
        color: str,
        tag: str = "",
    ) -> None:
        """登记一条边。`tag` 区分同一对端点上的多条边（用规则 id）。

        同一个 (source, target) 被多条规则连上时不能覆盖：两张不同的战利品表
        都掉同一个物品，图上应当是两条独立边，而不是一条 `/` 拼接的标签。
        """
        key = (source, target, tag)
        self.graph.edges[key] = (label, tooltip)
        self.graph.edge_colors[key] = color

    # ---- 规则选择 ----

    def live_rules(self, head: str) -> list[Rule]:
        """body 全为 TRUE 的规则，按 (body 长度, id) 排序——与 `ra why` 同序。"""
        live = [
            rule
            for rule in self.rules_by_head.get(head, [])
            if rule.kind not in DROP_KINDS
            and all(self.result.of(t) is State.TRUE for t in rule.body)
        ]
        return sorted(live, key=lambda r: (len(r.body), r.id))

    def blocked_rules(self, head: str) -> list[tuple[Rule, list[str]]]:
        """body 里有 FALSE / UNKNOWN 的规则，连同它们的缺项。

        这类规则不画边（画出来就是一片死分支，把一个 37 条规则的小图撑成一团），
        但**必须报数**：只画 TRUE 的那部分，读者会把「画出来的这些」默认成
        「全部途径」，而实际还有若干条因为缺项走不通。

        与 `--max-groups` / `--branches` 的截断是两个问题：截断是「看得见但没
        铺开」，补法是加预算；这里是「根本走不通」，补法是补事实。所以两者
        分开计数、分开标注。
        """
        out: list[tuple[Rule, list[str]]] = []
        for rule in self.rules_by_head.get(head, []):
            if rule.kind in DROP_KINDS:
                continue
            bad = [t for t in rule.body if self.result.of(t) is not State.TRUE]
            if bad:
                out.append((rule, bad))
        return out

    def upstream(self, rule: Rule) -> list[str]:
        """规则的入边成员。

        条件默认不进上游：它们已经写在菱形标签里。再画成节点，三条虚线汇进
        同一个菱形，读者分不清哪条是「东西从哪来」、哪条是「要什么」。
        `expand_conditions` 时照常展开，标签同时不再重复写。
        """
        body = list(rule.body)
        if self.expand_conditions:
            return body
        kept = [b for b in body if not is_condition(b)]
        self.graph.folded_conditions += len(body) - len(kept)
        return kept

    # ---- 遍历 ----

    def visit(self, value: str, depth: int, path: frozenset[str]) -> None:
        if depth >= self.max_depth:
            self._value(value, cut=True)
            return

        sort = split_node(value)[0]
        if sort in ROOT_SORTS:
            self._value(value, root=True)
            return

        # 条件（设备 / 工具 / 附魔）默认只画节点，不往上追问。
        # 追问下去会拉出「铁镐 ← 三根铁锭 ← 铁矿石 ← …」，而读者此刻只想看
        # 「这个物品需要什么」。
        if is_condition(value) and not self.expand_conditions:
            self._value(value, label=condition_label(value))
            self.graph.condition_leaves += 1
            return

        # L1：tag 只画节点，不展开成员。`tag ← item` 说的是「谁是成员」，
        # 不是「怎么获得」，展开它只是把 13 种木台阶铺成一列。
        if sort == "tag" and not self.expand_tags:
            members = self.rules_by_head.get(value, [])
            self._value(value, label=f"{short(value)}\\n{len(members)} 种成员")
            self.graph.folded_tags += len(members)
            return

        rules = self.live_rules(value)
        blocked = self.blocked_rules(value)
        if not rules:
            # TRUE 却没有可展开的规则：种子，或规则被预算挡掉
            self._value(value, leaf=True)
            self._blocked(value, blocked)
            return

        self._value(value)
        self._blocked(value, blocked)

        # L2：同 head 的多条规则按来源类别分组，够数的聚成组节点
        buckets: dict[str, list[Rule]] = {}
        for rule in rules:
            buckets.setdefault(category_of(rule)[0], []).append(rule)
        ordered = sorted(buckets.values(), key=lambda rs: (-len(rs), category_of(rs[0])[0]))

        # 类别数上限：只裁极端情形（一个物品几十种来源）。同类的重复规则
        # 由组节点吸收，不靠这里裁。
        chosen_groups = ordered[: self.max_groups] if self.max_groups > 0 else ordered
        for group in chosen_groups:
            if len(group) >= self.group_min:
                self._emit_group(value, group, depth, path)
            else:
                for rule in group:
                    self._emit_rule(value, rule, depth, path)

        remaining = sum(len(g) for g in ordered[len(chosen_groups):])
        if remaining:
            self._omitted(value, remaining, reason="受 --max-groups 限制")

    def _emit_group(
        self, value: str, rules: list[Rule], depth: int, path: frozenset[str]
    ) -> None:
        """一组同类来源：一个组节点直连产物，内部规则默认不铺开。"""
        key = self._group(value, rules)
        label, color = kind_style(rules[0].kind, value)
        self._edge(key, value, label, f"{len(rules)} 条同类来源", color, tag=key)

        # 组内规则全部是「单前件且是全局起点」时，folder 的上游就是那个起点。
        # 默认不展开组内规则，所以上这些起点边根本不在图上；记下来让
        # `absorb_roots` 写进产物标签——否则 folder 会变成无源节点。
        if all(len(rule.body) == 1 for rule in rules):
            sources = {rule.body[0] for rule in rules}
            if len(sources) == 1:
                (only,) = sources
                if split_node(only)[0] in ROOT_SORTS:
                    # 用类别名（「生成」）而不是边的 kind 文字（「获得」）：
                    # folder 上的标签就是类别名，两处必须一致。
                    self.graph.pending_roots.setdefault(value, []).append(
                        (only, category_of(rules[0])[1])
                    )

        if not self.expand_groups:
            return
        shown = rules if self.max_branches <= 0 else rules[: self.max_branches]
        for rule in shown:
            self._emit_rule(value, rule, depth, path, from_group=key)
        if len(rules) > len(shown):
            # 被挡住的上游记下来：同构折叠要据此判断「这个 tag 的成员本该都在图上」。
            # 单前件规则的唯一前件就是成员；多前件时记全部成员（保守，
            # 多一点不影响 `len(expected) * 2 < len(cluster.members)` 的比较方向）。
            for rule in rules[len(shown) :]:
                self.graph.suppressed.update(rule.body)
            self._omitted(key, len(rules) - len(shown), reason="组内受 --branches 限制")

    def _emit_rule(
        self,
        value: str,
        rule: Rule,
        depth: int,
        path: frozenset[str],
        *,
        from_group: str | None = None,
    ) -> None:
        body = self.upstream(rule)
        label, color = kind_style(rule.kind, rule.head)

        # 单前件、且没有条件：不画菱形，把规则压成一条边。
        #
        # 图上绝大多数链是「一个前置 → 一个产物」（世界生成方块、方块有战利品表）。
        # 给每节都画菱形，一条挖矿链就是三个菱形，而它们没有任何信息可表达——
        # 菱形只在「有 AND 关系要讲」时才有意义：多个原料，或工具/附魔这类条件。
        #
        # **有条件就必须留菱形**：条件写在菱形内部（见 `rule_label`），压成边
        # 就只能塞进边标签，一长串挤在箭头上没法读，也失去了「这条规则的完整前提
        # 是一个整体」这个结构。
        has_conditions = any(is_condition(b) for b in rule.body)
        if len(body) == 1 and not has_conditions and from_group is None:
            target = body[0]
            if target in path:
                self._value(target, cut=True)
                self._edge(target, value, "（环）", rule.id, "#cbd5e1", tag=rule.id)
                return
            self._edge(
                target,
                value,
                edge_label(rule, inline_conditions=not self.expand_conditions),
                rule.id,
                color,
                tag=rule.id,
            )
            if is_condition(target):
                # 条件不是「来源」，用虚线：它不给东西，只限制能不能拿
                self.graph.condition_edges.add((target, value, rule.id))
                self.graph.edge_colors[(target, value, rule.id)] = CONDITION_COLOR
            self.graph.merged.add(rule.id)
            self._templates(rule, value, dashed=True)
            self.visit(target, depth + 1, path | {target})
            return

        rule_key = self._rule(rule)
        self._edge(rule_key, value, label, rule.id, color, tag=rule.id)
        if from_group is not None:
            self._edge(from_group, rule_key, "", rule.id, color, tag=rule.id)

        for target in body:
            if target in path:
                self._value(target, cut=True)
                self._edge(target, rule_key, "（环）", rule.id, "#cbd5e1", tag=rule.id)
                continue
            # 前置 → 规则：同一条规则的多条入边共用一种颜色
            self._edge(target, rule_key, "", rule.id, color, tag=rule.id)
            if is_condition(target):
                self.graph.condition_edges.add((target, rule_key, rule.id))
                self.graph.edge_colors[(target, rule_key, rule.id)] = CONDITION_COLOR
            self.visit(target, depth + 1, path | {target})
        self._templates(rule, rule_key)

    def _templates(self, rule: Rule, anchor: str, *, dashed: bool = False) -> None:
        """`seeds` / `bindings` 规则里的 `meta.templates` 合成一张便签。

        「这个方块来自哪个结构模板」是 `bindings` 族已经记录的事实（`meta.templates`），
        但规则 body 只到 `world:` 为止。图上补出模板，才回答得了「哪来的」。

        多个模板各画一个节点会把图横向拉宽一倍，而它们的关系是同一条规则的并列
        出处，所以合并成一个多行便签——与「一条规则一个菱形」是同一个思路。

        `dashed=True` 时这条边是虚线：模板是**附加信息**，不是获取前提。
        单前件规则合并后锚点是产物本身，实线会被误读成「还有另一个来源」。
        """
        templates = [t for t in rule.meta.get("templates") or [] if isinstance(t, str)]
        if not templates:
            return
        key = f"templates::{rule.id}"
        shown = templates[:6]
        lines = [short_template(t) for t in shown]
        if len(templates) > len(shown):
            lines.append(f"…另有 {len(templates) - len(shown)} 个模板")
        self.graph.nodes[key] = {
            "sort": "template",
            "label": "\\l".join(["模板出处："] + lines) + "\\l",
            "tooltip": "\n".join(templates),
        }
        self._edge(key, anchor, "", rule.id, "#b45309", tag=rule.id)
        if dashed:
            self.graph.dashed.add((key, anchor, rule.id))

    def _omitted(self, value: str, count: int, *, reason: str) -> None:
        key = f"omitted::{value}"
        self.graph.nodes[key] = {
            "sort": "omitted",
            "label": f"另有 {count} 条来源（未展开）",
        }
        self._edge(key, value, "", reason, "#fb923c", tag=key)
        self.graph.omitted[value] = count

    def _blocked(self, value: str, entries: list[tuple[Rule, list[str]]]) -> None:
        """把「走不通的途径」画成一张显式便签，带缺项统计。

        不画真边：缺项节点本身是 FALSE，接到图上会让「来源」与「不存在的来源」
        混为一谈，而 FALSE 分支往往几十条（绿宝石图 37 条）。便签只说「还有
        这些走不通」，明细进 tooltip——既不假装它们不存在，也不让死分支挤走活分支。
        """
        if not entries:
            return
        key = f"blocked::{value}"
        missing = Counter()
        for _, bad in entries:
            for node in bad:
                missing[node] += 1
        shown = missing.most_common(3)
        # 一行一个：理由同 `_group`——缺项名往往带路径，挤一行会拉宽便签。
        headline = stacked(short(node) for node, _ in shown)
        if len(missing) > len(shown):
            headline += f"\\n等 {len(missing)} 项"
        self.graph.nodes[key] = {
            "sort": "blocked",
            "label": f"另有 {len(entries)} 条走不通\\n缺：{headline}",
            "tooltip": f"{len(entries)} 条规则的 body 含 FALSE / UNKNOWN，未画出：\n"
            + "\n".join(
                f"{rule.id}  缺 {', '.join(short(t) for t in bad)}"
                for rule, bad in entries[:12]
            ),
        }
        # 虚线：它不是一条获取途径，是「这里还有别的路但不通」的提示
        self._edge(key, value, "", f"{len(entries)} 条走不通", "#dc2626", tag=key)
        self.graph.dashed.add((key, value, key))
        self.graph.blocked[value] = len(entries)
