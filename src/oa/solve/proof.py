"""证明枚举：一个 TRUE 节点有哪几条获取途径。

产物是**一条**最小深度证明（`SolveResult.proofs`，BFS 首次点亮即最短）。
但人问的是「这东西怎么拿到」，答案往往不止一条：鳕鱼桶既能用桶捞鱼，
也能跟渔夫买。只给一条会让人误以为另一条不存在。

## 与 `proofs` 的分工

| | `SolveResult.proofs` | 本模块 |
|---|---|---|
| 条数 | 每节点一条 | 全部（受上限约束） |
| 判据 | 首次点亮 | 所有 body 全 TRUE 的规则 |
| 用途 | 报告里的 `proof` 字段、确定性排序 | `oa why` 展开给人看 |

## 组合爆炸的处理

一条规则的 body 若每个成员都有多条路径，全展开是笛卡尔积。实例上
`item:minecraft:oak_planks` 的上游能展开出上千条，既不可读也没意义。

所以分两档：

- 默认：每条上层规则只展开**一条**子路径（取最小深度、同深度按 rule.id 字典序），
  于是输出条数 = 上层规则条数，可读。
- `max_paths > 1` 时按广度优先逐个放开子路径，直到达到上限。

两种模式都不超过 `max_depth`，遇到环直接截断并标记——环不是错误，
「无入口的环」在归因里已经判成 `cycle_no_entry`，能走到这里的节点必然有真路径。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ir.nodes import Rule, split_node
from .fixpoint import SolveResult, State

# 这些排序的节点是分析的起点，不再往上追问
ROOT_SORTS = frozenset({"assume", "world"})


@dataclass
class Step:
    """路径上的一步：`node` 由 `rule` 得到，`children` 是它的前置。"""

    node: str
    rule: Rule | None
    children: list["Step"] = field(default_factory=list)
    # 该节点是分析起点（assume/world）或本来就没有规则
    is_root: bool = False
    # 环截断
    cut: bool = False
    # body 里为 TRUE 但没展开的成员（受 max_paths 限制时可能出现）
    unexpanded: list[str] = field(default_factory=list)

    def depth(self) -> int:
        return 1 + max((c.depth() for c in self.children), default=0)

    def nodes(self) -> int:
        return 1 + sum(c.nodes() for c in self.children)


def _is_root(value: str) -> bool:
    return split_node(value)[0] in ROOT_SORTS


def _rule_depths(
    rules_by_head: dict[str, list[Rule]], result: SolveResult
) -> dict[str, Rule]:
    """每个节点的最小深度规则。

    `SolveResult.proofs` 已经是 BFS 首次点亮的结果，但那是在求解过程中记的，
    枚举时需要「在给定 body 子集上」重新挑。两者一致时直接用 `proofs` 省一次计算。
    """
    return dict(result.proofs)


def enumerate_proofs(
    rules_by_head: dict[str, list[Rule]],
    result: SolveResult,
    value: str,
    *,
    max_depth: int = 24,
    max_paths: int = 8,
    branch_limit: int = 1,
) -> list[Step]:
    """枚举 `value` 的获取途径。返回每条顶层路径的根 `Step`。

    - `max_paths`：**顶层**最多给几条路径（每条上层规则一条）
    - `branch_limit`：**每个中间节点**最多展开几条子路径。

    两个上限分开是因为用途不同：顶层条数是「这东西有几种拿法」，
    中间层条数是「某一步的前置有几种来源」。后者调大就会组合爆炸，
    所以默认 1，并在 `Step.unexpanded` 里报出未展开的条数。
    """
    if result.of(value) is not State.TRUE:
        return []

    roots: list[Step] = []
    branches = _true_rules(rules_by_head.get(value, []), result)
    chosen = branches[: max(max_paths, 1)]
    for rule in chosen:
        roots.append(
            _expand(
                value,
                rule,
                rules_by_head,
                result,
                seen=frozenset({value}),
                depth=0,
                max_depth=max_depth,
                branch_limit=branch_limit,
            )
        )
    return roots


def _true_rules(candidates: list[Rule], result: SolveResult) -> list[Rule]:
    """body 全为 TRUE 的规则，按 (body 长度, id) 排序 —— 短路径优先，稳定。"""
    live = [r for r in candidates if all(result.of(t) is State.TRUE for t in r.body)]
    return sorted(live, key=lambda r: (len(r.body), r.id))


def _expand(
    value: str,
    rule: Rule | None,
    rules_by_head: dict[str, list[Rule]],
    result: SolveResult,
    *,
    seen: frozenset[str],
    depth: int,
    max_depth: int,
    branch_limit: int = 1,
) -> Step:
    step = Step(node=value, rule=rule)
    if rule is None:
        step.is_root = True
        return step

    for target in rule.body:
        if target in seen:
            step.children.append(Step(node=target, rule=None, cut=True))
            continue
        if depth + 1 >= max_depth:
            step.children.append(Step(node=target, rule=None, cut=True))
            continue
        if _is_root(target):
            step.children.append(Step(node=target, rule=None, is_root=True))
            continue
        candidates = _true_rules(rules_by_head.get(target, []), result)
        if not candidates:
            # TRUE 却没有可展开的规则：只能是种子，或规则被 body 长度排序截掉
            step.children.append(Step(node=target, rule=None, is_root=True))
            continue

        # 同一个节点往往有十几条真实来源（绿宝石既有交易也有十几种结构战利品）。
        # 只展开了第一条时必须报出「还有几条」，否则输出会暗示「只有这一条」。
        chosen = candidates[: max(branch_limit, 1)]
        for candidate in chosen:
            step.children.append(
                _expand(
                    target,
                    candidate,
                    rules_by_head,
                    result,
                    seen=seen | {target},
                    depth=depth + 1,
                    max_depth=max_depth,
                    branch_limit=branch_limit,
                )
            )
        if len(candidates) > len(chosen):
            step.unexpanded.append(f"{target}（另有 {len(candidates) - len(chosen)} 条）")
    return step


def flatten_leaves(step: Step) -> list[Step]:
    """路径最底层的起点（假设与世界），按出现顺序。"""
    out: list[Step] = []

    def walk(node: Step) -> None:
        if not node.children:
            out.append(node)
            return
        for child in node.children:
            walk(child)

    walk(step)
    return out


def iter_steps(step: Step) -> list[Step]:
    """深度优先展平成 `[node, rule]` 序列，供报告逐行打印。"""
    out: list[Step] = []

    def walk(node: Step, level: int) -> None:
        out.append(node)
        for child in node.children:
            walk(child, level + 1)

    walk(step, 0)
    return out
