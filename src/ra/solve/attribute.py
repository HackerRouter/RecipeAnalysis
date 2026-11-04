"""不可达归因。

归因的四类：

| 归因 | 判据 | 输出 |
|---|---|---|
| `no_rule` | 无任何产出规则 | 兼查「是不是技术/创造物品」 |
| `blocked` | 所有规则 `FALSE` | 取 body 中 `FALSE` 最少的规则，列出缺项 |
| `undetermined` | 存在 `UNKNOWN` 规则且无 `TRUE` | 列出未知依赖与对应台账项 |
| `cycle_no_entry` | 依赖图 SCC 内无外部 `TRUE` 入口 | 环成员列表 |

环只是**解释**，不是求解特判：最小不动点天然不点亮无入口的环，
SCC 只在归因时用来把「互相等待」讲清楚。

## 为什么用 SCC 而不是找一条回路

SCC 一次算完，且判据只看分量性质；找回路有两个问题：

1. **会误判**：两个节点互相引用不等于没有入口。比如 `furnace` 有 `block:furnace ⇄ item:furnace`
   的回路，但另有配方入口，不构成「无入口的环」。按「缺项最少的规则」查到回路就
   报 `cycle_no_entry`，会把可达物品报成环死锁。
2. **很慢**：回溯时移除 `seen`，同一节点被反复访问，数据量一大就卡住。

所以改用一次 Kosaraju SCC：`cycle_no_entry` 的判据是
「该节点所在分量没有任何成员可达、且分量大小 > 1」。

## 为什么取「缺项最少」的规则

一条规则可能因为十几种前置缺失而 FALSE。列全部会让归因不可读，
也不指向下一步该补什么。取缺项最少的那条 = 「差一步就能拿到」的那条路径，
它最有行动价值。其余规则的缺项记进 `alternatives`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ir.nodes import Rule, RuleSet, split_node
from .fixpoint import SolveResult, State
from .scc import component_members, strongly_connected

# 归因类别
NO_RULE = "no_rule"
UNOBTAINABLE = "unobtainable"
BLOCKED = "blocked"
UNDETERMINED = "undetermined"
CYCLE = "cycle_no_entry"


@dataclass
class Attribution:
    """一个节点的归因结果。"""

    node: str
    reason: str
    # blocked：最能说明问题的那条规则及其缺项
    rule: Rule | None = None
    missing: list[str] = field(default_factory=list)
    # cycle：环成员
    cycle: list[str] = field(default_factory=list)
    note: str = ""
    # blocked：其它也走不通的规则，只给 id，供人工深挖
    alternatives: list[str] = field(default_factory=list)

    def as_json(self) -> dict:
        payload: dict = {
            "node": self.node,
            "reason": self.reason,
            "missing": self.missing,
        }
        if self.rule is not None:
            payload["rule"] = self.rule.id
            payload["prov"] = self.rule.prov.as_json() if self.rule.prov else None
        if self.alternatives:
            payload["alternatives"] = self.alternatives
        if self.cycle:
            payload["cycle"] = self.cycle
        if self.note:
            payload["note"] = self.note
        return payload


class Graph:
    """归因用的依赖图与 SCC 缓存。

    归因要对上千个节点跑，SCC 必须只算一次。
    """

    def __init__(self, rules: RuleSet, result: SolveResult) -> None:
        self.edges: dict[str, set[str]] = {}
        for rule in rules.rules:
            self.edges.setdefault(rule.head, set()).update(rule.body)
        self.component = strongly_connected(self.edges, set(result.states))
        self.members = component_members(self.component)
        # 分量内是否有任何成员为 TRUE（有入口）
        self.live: dict[int, bool] = {}
        for node, cid in self.component.items():
            if result.of(node) is State.TRUE:
                self.live[cid] = True

    def in_dead_cycle(self, node: str) -> list[str]:
        """`node` 是否处于「无外部入口且非同自环」的分量；返回成员。"""
        cid = self.component.get(node)
        if cid is None:
            return []
        members = self.members.get(cid, [])
        if len(members) < 2:
            return []
        if self.live.get(cid):
            return []
        return members


def _false_body(rule: Rule, result: SolveResult) -> list[str]:
    return [t for t in rule.body if result.of(t) is State.FALSE]


def attribute(
    value: str,
    rules: RuleSet,
    result: SolveResult,
    graph: Graph | None = None,
    exceptions: dict[str, dict] | None = None,
) -> Attribution:
    """给一个非 TRUE 节点归因。

    `exceptions` 是 `knowledge/maps/exceptions/unobtainable.json`：
    生存不可获取的例外表。命中它时 `reason` 细分为 `unobtainable`
    并带上类别，于是 `no_rule` 只剩「已知有机制但尚未提取」这一种含义。

    **例外表在其它归因之前生效**：这些物品往往*有*规则（挖掉掉自身、放置桥），
    只是那些规则构成无入口的环，或前置永远不成立。先看规则会得到
    `cycle_no_entry` / `blocked`，而这两种说法都在暗示「差一步就能拿到」。
    `petrified_oak_slab` 正是如此：有战利品表也有放置桥，两者互指，
    真实结论是「命令专用，生存拿不到」。
    """
    state = result.of(value)
    if state is State.TRUE:
        return Attribution(node=value, reason=NO_RULE, note="已可达，无需归因")

    kind, ident = split_node(value)
    # 例外表的键是注册名（`minecraft:air`），节点是 `item:minecraft:air`。
    # 两种都接受，免得表里写成长节点。
    table = exceptions or {}
    exception = table.get(value) or table.get(ident)
    if isinstance(exception, dict):
        return Attribution(
            node=value,
            reason=UNOBTAINABLE,
            note=f"{exception.get('category', '未分类')}：{exception.get('basis', '')}",
        )

    candidates = rules.of_head(value)

    if not candidates:
        note = ""
        if kind == "item":
            note = "有获取机制但尚未提取；属待补项，见 plan §11"
        elif kind in ("block", "entity", "structure", "world"):
            note = "无任何播种规则；该排序的节点应由世界生成事实提供"
        return Attribution(node=value, reason=NO_RULE, note=note)

    if state is State.UNKNOWN:
        unknown_deps = [t for r in candidates for t in r.body if result.of(t) is State.UNKNOWN]
        return Attribution(
            node=value,
            reason=UNDETERMINED,
            missing=sorted(set(unknown_deps)),
            note=result.unknown_reason.get(value, ""),
        )

    graph = graph if graph is not None else Graph(rules, result)
    cycle = graph.in_dead_cycle(value)

    # FALSE：所有规则都不成立，取缺项最少的那条
    ranked = sorted(candidates, key=lambda r: (len(_false_body(r, result)), r.id))
    best = ranked[0]
    missing = _false_body(best, result)
    alternatives = [r.id for r in ranked[1:4]]

    if cycle:
        return Attribution(
            node=value,
            reason=CYCLE,
            rule=best,
            missing=missing,
            cycle=cycle,
            alternatives=alternatives,
            note="所在强连通分量内无任何成员可达",
        )

    return Attribution(
        node=value,
        reason=BLOCKED,
        rule=best,
        missing=missing,
        alternatives=alternatives,
    )
