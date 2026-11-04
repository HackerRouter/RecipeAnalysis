"""全量关系图的内部表示：落盘与读回。

## 格式

单个 JSON，字符串表 + 下标引用。三条要求各自对着一个选择：体积（同一个
serializer 名重复上千次，内联是主要膨胀来源）、可 diff（字符串表在前、
规则行在后，行序确定）、自足（规则 + 状态 + 种子同在一个文件，读回即可建图，
不必再过一遍求解）。不用 pickle / SQLite：前者不可移植也不可读，后者对
几 MB 的只读产物是过度设计。完整对比与实测数字见
`docs/adr/0020-graph-representation-and-rendering.md`。

## 三值状态

`true` 与 `unknown` 一起存；缺席的节点按 `FALSE` 处理——这与
`SolveResult.of` 的语义一致，不是省略。

## 契约

`GRAPH_SCHEMA` 变更即产物不兼容。读到不认识的版本必须报错，不能尽力解析：
一份被误解半截的图会画出不存在的路径，比直接失败糟得多。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ...facts.schema import Prov
from ...ir.nodes import Rule, RuleSet
from ...solve.fixpoint import SolveResult, State

# 内部表示的格式版本。字段变化即 +1。
GRAPH_SCHEMA = 1

# 文件名固定：一个版本一份，随 `ra graph` 覆盖
GRAPH_FILE = "graph.json"


class GraphFormatError(Exception):
    """内部表示文件不可用（版本不符、缺字段、结构损坏）。"""


@dataclass
class GraphHeader:
    """文件头部的可读信息。读回时用它做兼容性判断与展示。"""

    graph_schema: int
    ir_schema: int
    label: str
    rule_count: int
    node_count: int
    facts_digest: dict[str, int]


class _Strings:
    """双向字符串表。同一字符串只存一次，规则行用下标引用。"""

    def __init__(self) -> None:
        self.items: list[str] = []
        self.index: dict[str, int] = {}

    def add(self, text: str) -> int:
        found = self.index.get(text)
        if found is None:
            found = len(self.items)
            self.index[text] = found
            self.items.append(text)
        return found

    def get(self, seq: int) -> str:
        if seq < 0:
            raise GraphFormatError(f"字符串下标越界：{seq}")
        try:
            return self.items[seq]
        except IndexError as exc:
            raise GraphFormatError(f"字符串下标越界：{seq}（共 {len(self.items)} 条）") from exc


@dataclass
class SerializedGraph:
    """内存中的内部表示，可直接 `to_json()`。"""

    header: GraphHeader
    strings: list[str]
    rules: list[list]
    true_nodes: list[str]
    unknown_nodes: dict[str, str]
    seeds: list[str]
    stats: dict[str, int]

    def as_json(self) -> dict:
        return {
            "graph_schema": self.header.graph_schema,
            "ir_schema": self.header.ir_schema,
            "label": self.header.label,
            "rule_count": self.header.rule_count,
            "node_count": self.header.node_count,
            "facts_digest": self.header.facts_digest,
            "stats": self.stats,
            "seeds": self.seeds,
            "strings": self.strings,
            "rules": self.rules,
            "states": {
                "true": self.true_nodes,
                "unknown": self.unknown_nodes,
            },
        }

    def to_json(self) -> str:
        """紧凑编码：体积比缩进版小一半，而不影响可 diff（行序确定）。"""
        return json.dumps(
            self.as_json(), ensure_ascii=False, separators=(",", ":"), sort_keys=False
        )


def serialize_graph(
    rule_set: RuleSet,
    result: SolveResult,
    seeds: list[str],
    *,
    label: str,
    ir_schema: int,
    facts_digest: dict[str, int],
) -> SerializedGraph:
    """把规则集与求解结果收成一个可落盘的结构。

    `meta` 与 `prov` 走字符串表（按 JSON 编码去重）：同一个 serializer 名会出现
    上千次，逐行内联是主要膨胀来源。
    """
    strings = _Strings()
    rows: list[list] = []

    for rule in rule_set.rules:
        prov = rule.prov
        rows.append(
            [
                strings.add(rule.id),
                strings.add(rule.head),
                [strings.add(t) for t in rule.body],
                [strings.add(t) for t in rule.soft],
                strings.add(rule.kind),
                strings.add(rule.family),
                strings.add(json.dumps(rule.meta, ensure_ascii=False, sort_keys=True)),
                strings.add(
                    json.dumps(
                        [prov.input, prov.file, prov.ptr] if prov else None,
                        ensure_ascii=False,
                    )
                ),
            ]
        )

    true_nodes = sorted(n for n, s in result.states.items() if s is State.TRUE)
    unknown_nodes = {
        n: result.unknown_reason.get(n, "")
        for n, s in result.states.items()
        if s is State.UNKNOWN
    }

    return SerializedGraph(
        header=GraphHeader(
            graph_schema=GRAPH_SCHEMA,
            ir_schema=ir_schema,
            label=label,
            rule_count=len(rule_set.rules),
            node_count=len(result.states),
            facts_digest=dict(sorted(facts_digest.items())),
        ),
        strings=strings.items,
        rules=rows,
        true_nodes=true_nodes,
        unknown_nodes=dict(sorted(unknown_nodes.items())),
        seeds=sorted(seeds),
        stats={
            "states": result.counts(),
            "iterations": result.iterations,
            "rules_true": result.rules_true,
            "rules_unknown": result.rules_unknown,
            "rules_false": result.rules_false,
        },
    )


def write_graph(graph: SerializedGraph, path: Path) -> None:
    """写内部表示。`newline="\\n"` 保证两个平台产物逐字节一致。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(graph.to_json() + "\n", encoding="utf-8", newline="\n")


def read_graph(path: Path) -> tuple[RuleSet, SolveResult, GraphHeader]:
    """读内部表示，还原 `RuleSet` 与 `SolveResult`。

    只认 `GRAPH_SCHEMA`。更高版本直接失败：字段含义变了却强行解析，
    会画出不存在的路径。
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GraphFormatError(f"内部表示不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise GraphFormatError(f"{path} 不是合法 JSON：{exc}") from exc

    if not isinstance(doc, dict):
        raise GraphFormatError(f"{path} 顶层不是对象")

    version = doc.get("graph_schema")
    if version != GRAPH_SCHEMA:
        raise GraphFormatError(
            f"{path} 的 graph_schema={version!r}，本程序只认 {GRAPH_SCHEMA}。"
            "重新跑 `ra graph --label <label>` 生成。"
        )

    for key in ("strings", "rules", "states", "ir_schema", "label"):
        if key not in doc:
            raise GraphFormatError(f"{path} 缺字段 {key!r}")

    strings = _Strings()
    strings.items = [str(s) for s in doc["strings"]]
    strings.index = {text: seq for seq, text in enumerate(strings.items)}

    rule_set = RuleSet()
    for seq, row in enumerate(doc["rules"]):
        if not isinstance(row, list) or len(row) != 8:
            raise GraphFormatError(f"{path}: 第 {seq} 条规则行形状不对：{row!r}")
        try:
            rule_set.add(_rule_from_row(row, strings))
        except GraphFormatError:
            raise
        except (ValueError, TypeError, IndexError) as exc:
            # 行里任何一处坏掉（下标越界、meta 不是 JSON、节点名不合法）
            # 都要变成格式错误：让 CLI 用一句话报出来，而不是抛一个谁也没
            # 准备接的异常。
            raise GraphFormatError(f"{path}: 第 {seq} 条规则行无法解析（{exc}）") from exc

    states = doc["states"]
    stats = doc.get("stats") or {}
    result = SolveResult(
        states={node: State.TRUE for node in states.get("true", [])},
        unknown_reason={str(k): str(v) for k, v in (states.get("unknown") or {}).items()},
        iterations=int(stats.get("iterations", 0)),
        rules_true=int(stats.get("rules_true", 0)),
        rules_unknown=int(stats.get("rules_unknown", 0)),
        rules_false=int(stats.get("rules_false", 0)),
    )
    for node in result.unknown_reason:
        result.states.setdefault(node, State.UNKNOWN)

    header = GraphHeader(
        graph_schema=int(version),
        ir_schema=int(doc["ir_schema"]),
        label=str(doc["label"]),
        rule_count=int(doc.get("rule_count", len(rule_set.rules))),
        node_count=int(doc.get("node_count", 0)),
        facts_digest={str(k): int(v) for k, v in (doc.get("facts_digest") or {}).items()},
    )
    return rule_set, result, header


def _rule_from_row(row: list, strings: _Strings) -> Rule:
    rid, head, body, soft, kind, family, meta_json, prov_json = row
    prov_raw = json.loads(strings.get(prov_json))
    return Rule(
        id=strings.get(rid),
        head=strings.get(head),
        body=tuple(strings.get(t) for t in body),
        soft=tuple(strings.get(t) for t in soft),
        kind=strings.get(kind),
        family=strings.get(family),
        meta=json.loads(strings.get(meta_json)),
        prov=Prov(*prov_raw) if prov_raw else None,
    )
