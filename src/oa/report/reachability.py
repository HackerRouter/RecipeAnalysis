"""可达性报告。

产物：

| 文件 | 内容 |
|---|---|
| `reachability.jsonl` | 每身份一行：`status / proof / alternatives / blocked_by` |
| `coverage.json` | 未解释输入、未映射项、约定覆盖率、`UNKNOWN` 分布 |
| `run.json` | 输入摘要、`Profile`、适配器版本、IR schema、计数 |

`run.json` 缺任一项不可复算——这是 AGENTS.md 红线 4 对产物的要求。

## 为什么按身份而不是按节点

下游问的是「这个物品能不能拿到」。`tag:` / `station:` / `block:` 这些节点是推理的
中间产物，不是结论。所以 `reachability.jsonl` 只列 `item:` 节点，
其余节点的状态进 `coverage.json` 的分布统计。

## 未覆盖物品的归因要能指向下一步

`blocked` 列出缺项最少的规则；`undetermined` 列出未知依赖。
两者都指向「该补什么事实」，而不是「这个物品不行」。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ..ir.nodes import RuleSet, split_node
from ..solve.attribute import NO_RULE, UNOBTAINABLE, Attribution, Graph, attribute
from ..solve.fixpoint import SolveResult, State


@dataclass
class ReachabilityReport:
    rows: list[dict]
    counts: dict[str, int]
    attributions: dict[str, Attribution]

    @property
    def rate(self) -> float:
        total = sum(self.counts.values())
        return self.counts.get(State.TRUE.value, 0) / total if total else 0.0


def build_reachability(
    rules: RuleSet,
    result: SolveResult,
    identities: list[str] | None = None,
    exceptions: dict[str, dict] | None = None,
) -> ReachabilityReport:
    """按身份生成可达性结论与归因。

    `identities` 是待判定的全集，调用方应传 `registries.json` 的 `minecraft:item`。
    **不传时会退化成「规则里出现的 item 节点」**——那样没有规则的物品会从报告里
    彻底消失，只在总数上少几个，看不出来。运行期导出是唯一能给出注册表全集
    的途径，因此生产路径必须显式传。

    `exceptions` 是生存不可获取的例外表（`knowledge/maps/exceptions/unobtainable.json`），
    用来把 `no_rule` 拆成「确定拿不到」与「机制尚未提取」。
    """
    items = sorted(
        value for value in rules.nodes() if split_node(value)[0] == "item"
    )
    if identities is None:
        identities = items

    graph = Graph(rules, result)

    rows: list[dict] = []
    attributions: dict[str, Attribution] = {}
    counts: Counter = Counter()

    for value in identities:
        state = result.of(value)
        counts[state.value] += 1
        candidates = rules.of_head(value)

        row: dict = {
            "node": value,
            "status": state.value,
            "alternatives": len(candidates),
        }

        if state is State.TRUE:
            proof = result.proofs.get(value)
            row["proof"] = _proof_chain(value, result)
            if proof is not None:
                row["rule"] = proof.id
                row["family"] = proof.family
                row["kind"] = proof.kind
                row["prov"] = proof.prov.as_json() if proof.prov else None
                row["meta"] = proof.meta
        else:
            attribution = attribute(value, rules, result, graph, exceptions)
            attributions[value] = attribution
            row["reason"] = attribution.reason
            if attribution.rule is not None:
                row["rule"] = attribution.rule.id
                row["prov"] = (
                    attribution.rule.prov.as_json() if attribution.rule.prov else None
                )
            if attribution.missing:
                row["blocked_by"] = attribution.missing
            if attribution.cycle:
                row["cycle"] = attribution.cycle
            if attribution.note:
                row["note"] = attribution.note

        rows.append(row)

    return ReachabilityReport(
        rows=rows,
        counts=dict(counts),
        attributions=attributions,
    )


def _proof_chain(value: str, result: SolveResult, limit: int = 24) -> list[dict]:
    """沿证明树展开最小深度的一条链。

    只作为人读的摘要，不保证覆盖所有前置——完整证明由 `oa why` 按需展开。
    """
    chain: list[dict] = []
    frontier = [value]
    seen: set[str] = {value}
    while frontier and len(chain) < limit:
        current = frontier.pop(0)
        rule = result.proofs.get(current)
        if rule is None:
            continue
        chain.append({"node": current, "rule": rule.id, "body": list(rule.body)})
        for target in rule.body:
            if target in seen:
                continue
            seen.add(target)
            frontier.append(target)
    return chain


def build_coverage(
    rules: RuleSet,
    result: SolveResult,
    compile_report: dict,
) -> dict:
    """覆盖率与未映射项。"""
    by_sort: Counter = Counter()
    by_status: dict[str, Counter] = {}
    for value, state in result.states.items():
        sort, _ = split_node(value)
        by_sort[sort] += 1
        by_status.setdefault(sort, Counter())[state.value] += 1

    return {
        "nodes_by_sort": dict(sorted(by_sort.items())),
        "status_by_sort": {
            sort: dict(counter) for sort, counter in sorted(by_status.items())
        },
        "rule_families": rules.family_counts(),
        "rule_states": {
            "true": result.rules_true,
            "unknown": result.rules_unknown,
            "false": result.rules_false,
            "iterations": result.iterations,
        },
        "compile": compile_report,
    }


def build_run_manifest(
    *,
    label: str,
    content_commit: str | None,
    source_repo: str | None,
    jar_sha256: str | None,
    ir_schema: int,
    adapter_versions: dict[str, int],
    facts_digest: dict[str, int],
    compile_report: dict,
    reachability: ReachabilityReport,
) -> dict:
    """`run.json`：缺前两项不可复算（AGENTS.md 红线 4）。

    `content_commit` 与 `source_repo` 由输入配置的 `[source]` 段给出，未配置即为
    `null`。反编译源码树不必带 git 历史。
    """
    return {
        "label": label,
        "content_commit": content_commit,
        "source_repo": source_repo,
        "jar_sha256": jar_sha256,
        "ir_schema": ir_schema,
        "adapter_versions": dict(sorted(adapter_versions.items())),
        "facts_digest": dict(sorted(facts_digest.items())),
        "reachability": {
            "identities": sum(reachability.counts.values()),
            "rate": round(reachability.rate, 4),
            "by_status": reachability.counts,
        },
        "compile": compile_report,
    }


def write_reachability(path: Path, report: ReachabilityReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in report.rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def gap_rows(report: ReachabilityReport) -> list[dict]:
    """`gaps.jsonl`：不属于 `no_rule` 的不可达项，即「有路径但走不通」。

    `unobtainable` 不入本文件：它不是缺口，是已解释的结论。
    两类在 `reachability.jsonl` 里都能查到（带 `reason` 与 `note`）。
    """
    rows: list[dict] = []
    for value, attribution in sorted(report.attributions.items()):
        if attribution.reason in (NO_RULE, UNOBTAINABLE):
            continue
        rows.append(attribution.as_json())
    return rows
