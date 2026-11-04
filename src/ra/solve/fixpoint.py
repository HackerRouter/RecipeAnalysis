"""三值最小不动点。

规则：

- 节点状态 `{TRUE, FALSE, UNKNOWN}`
- 一条规则：`body` 全 `TRUE` → `TRUE`；任一 `FALSE` → `FALSE`；否则 `UNKNOWN`
- 一个节点：任一规则 `TRUE` → `TRUE`；否则任一规则 `UNKNOWN` → `UNKNOWN`；
  否则 `FALSE`。无规则 = `FALSE`
- 初始：`assume:*` 与 `world:*` 播种为 `TRUE`，其余 `FALSE`
- 迭代到不动点

Kleene 三值逻辑单调，迭代必然终止。用工作队列而不是每轮全扫。

## UNKNOWN 只表达「数据里查不到」

它不表达「可能存在」，也不表达「大概是不可达」。本项目里 UNKNOWN 有两个具体来源：

1. **规则标了 `uncertain`**：该规则的硬前置里有内容不可得的部分
   （如 `match_tool`——事实里只有条件类型，没有谓词具体内容）
2. **body 里有 UNKNOWN 节点**：不确定性沿链传播

没有规则且不在播种集的节点是 `FALSE`，不是 `UNKNOWN`——「确实没有获取路径」
与「我们查不到」必须分开，否则归因无法指向要补的事实。

## soft 完全不参与

`soft` 是状态约束（颜色、朝向、是否已剪），不阻塞可达性。求解器不读它。
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

from ..ir.nodes import Rule, RuleSet


class State(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


# 三值∧：任一 FALSE → FALSE；有 UNKNOWN → UNKNOWN；全 TRUE → TRUE
_AND_TABLE = {
    (State.TRUE, State.TRUE): State.TRUE,
    (State.TRUE, State.FALSE): State.FALSE,
    (State.TRUE, State.UNKNOWN): State.UNKNOWN,
    (State.FALSE, State.FALSE): State.FALSE,
    (State.FALSE, State.UNKNOWN): State.FALSE,
    (State.UNKNOWN, State.UNKNOWN): State.UNKNOWN,
}


def conj(left: State, right: State) -> State:
    key = (left, right) if (left, right) in _AND_TABLE else (right, left)
    return _AND_TABLE[key]


@dataclass
class SolveResult:
    """求解产物。"""

    states: dict[str, State] = field(default_factory=dict)
    # 节点首次变 TRUE 时点亮的规则（证明树的根）
    proofs: dict[str, Rule] = field(default_factory=dict)
    # 哪些节点被判 UNKNOWN 及原因
    unknown_reason: dict[str, str] = field(default_factory=dict)
    iterations: int = 0
    rules_true: int = 0
    rules_unknown: int = 0
    rules_false: int = 0

    def of(self, value: str) -> State:
        return self.states.get(value, State.FALSE)

    def counts(self) -> dict[str, int]:
        tally = {state.value: 0 for state in State}
        for state in self.states.values():
            tally[state.value] += 1
        return tally


class _Evaluator:
    """规则求值 + 依赖索引。"""

    def __init__(self, rules: RuleSet) -> None:
        self.rules = rules
        self.rules_by_id: dict[str, Rule] = {rule.id: rule for rule in rules.rules}
        # 节点 → 依赖它的规则（作为 body 成员）
        self.dependents: dict[str, list[Rule]] = defaultdict(list)
        for rule in rules.rules:
            for target in rule.body:
                self.dependents[target].append(rule)
        self.uncertain: dict[str, bool] = {
            rule.id: bool(rule.meta.get("uncertain")) for rule in rules.rules
        }

    def rule_state(self, rule: Rule, states: dict[str, State]) -> State:
        """规则本身的三值。"""
        outcome = State.TRUE
        for target in rule.body:
            # 无规则且未播种的节点是 FALSE
            outcome = conj(outcome, states.get(target, State.FALSE))
            if outcome is State.FALSE:
                return State.FALSE
        if outcome is State.TRUE and self.uncertain.get(rule.id):
            # body 全真但规则本身有查不到的内容
            return State.UNKNOWN
        return outcome


def solve(rules: RuleSet, seeds: list[str]) -> SolveResult:
    """求最小不动点。"""
    evaluator = _Evaluator(rules)
    result = SolveResult()

    states: dict[str, State] = {}
    for value in rules.nodes():
        states[value] = State.FALSE
    for value in seeds:
        states[value] = State.TRUE

    # 已求值的规则状态缓存，避免重复算
    rule_states: dict[str, State] = {}

    queue: deque[str] = deque(sorted(seeds))
    in_queue: set[str] = set(queue)

    while queue:
        value = queue.popleft()
        in_queue.discard(value)
        result.iterations += 1

        for rule in evaluator.dependents.get(value, []):
            before = rule_states.get(rule.id)
            if before is State.TRUE:
                continue
            after = evaluator.rule_state(rule, states)
            if after is before:
                continue
            rule_states[rule.id] = after

            if after is not State.TRUE:
                continue

            head = rule.head
            current = states.get(head, State.FALSE)
            if current is State.TRUE:
                continue
            states[head] = State.TRUE
            result.proofs[head] = rule
            if head not in in_queue:
                queue.append(head)
                in_queue.add(head)

    # TRUE 收敛后，剩余可达的 UNKNOWN 沿链传播一次到底。
    #
    # 不能再放进主循环：主循环只处理「变 TRUE」的推进，UNKNOWN 不推进任何东西。
    # 但 UNKNOWN 需要传下去，否则「依赖某个查不到的物品」会显示成「不可达」，
    # 归因就会指向错误的方向（应该指向要补的事实，而不是「无路径」）。
    for rule in rules.rules:
        rule_states.setdefault(rule.id, evaluator.rule_state(rule, states))
    _propagate_unknown(rules, evaluator, states, rule_states, result)

    result.states = states
    for rule in rules.rules:
        state = rule_states.get(rule.id, State.FALSE)
        if state is State.TRUE:
            result.rules_true += 1
        elif state is State.UNKNOWN:
            result.rules_unknown += 1
        else:
            result.rules_false += 1

    _explain_unknowns(rules, evaluator, states, rule_states, result)
    return result


def _propagate_unknown(
    rules: RuleSet,
    evaluator: _Evaluator,
    states: dict[str, State],
    rule_states: dict[str, State],
    result: SolveResult,
) -> None:
    """把 UNKNOWN 沿 body 传播，直到不再变化。"""
    changed = True
    while changed:
        changed = False
        for rule in rules.rules:
            head = rule.head
            if states.get(head) is State.TRUE:
                continue
            if rule_states.get(rule.id) is not State.FALSE:
                continue
            # 规则当前是 FALSE；若 body 里有 UNKNOWN 且无 FALSE，它应为 UNKNOWN
            outcome = State.TRUE
            for target in rule.body:
                outcome = conj(outcome, states.get(target, State.FALSE))
                if outcome is State.FALSE:
                    break
            if outcome is not State.UNKNOWN:
                continue
            rule_states[rule.id] = State.UNKNOWN
            if states.get(head) is State.FALSE:
                states[head] = State.UNKNOWN
                changed = True


def _explain_unknowns(
    rules: RuleSet,
    evaluator: _Evaluator,
    states: dict[str, State],
    rule_states: dict[str, State],
    result: SolveResult,
) -> None:
    """给每个 UNKNOWN 节点记下一条可读的原因。"""
    for value, state in states.items():
        if state is not State.UNKNOWN:
            continue
        causes: list[str] = []
        for rule in rules.of_head(value):
            if rule_states.get(rule.id) is not State.UNKNOWN:
                continue
            missing = [
                target
                for target in rule.body
                if states.get(target) is State.UNKNOWN
            ]
            if evaluator.uncertain.get(rule.id):
                causes.append(f"{rule.id}: 含内容不可得的硬前置")
            elif missing:
                causes.append(f"{rule.id}: 依赖 {', '.join(missing[:3])}")
        result.unknown_reason[value] = "；".join(causes[:2]) or "上游数据不可得"
