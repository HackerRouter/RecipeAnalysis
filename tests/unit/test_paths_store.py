"""内部表示的落盘与读回。

这组测试钉住三件事，任何一条坏掉都会让「画出来的图」与「事实」脱钩：

1. 读回的规则与状态与落盘前**完全一致**（否则图会画出不存在的路径）
2. 落盘**逐字节确定**（否则产物无法 diff、无法复算）
3. 版本不符**直接失败**（半截解析比失败糟得多）
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ra.facts.schema import Prov
from ra.ir.nodes import Rule, RuleSet
from ra.report.paths.store import (
    GRAPH_SCHEMA,
    GraphFormatError,
    read_graph,
    serialize_graph,
    write_graph,
)
from ra.solve.fixpoint import SolveResult, State


def _rules() -> RuleSet:
    rule_set = RuleSet()
    rule_set.add(
        Rule(
            id="recipe:planks",
            head="item:minecraft:oak_planks",
            body=("item:minecraft:oak_log",),
            kind="yield",
            family="recipes",
            meta={"serializer": "minecraft:crafting_shapeless", "count": 4},
            prov=Prov(input="src", file="recipe/oak_planks.json"),
        )
    )
    rule_set.add(
        Rule(
            id="loot:oak_log",
            head="item:minecraft:oak_log",
            body=("table:minecraft:blocks/oak_log",),
            kind="yield",
            family="loot",
            meta={"table": "minecraft:blocks/oak_log"},
            prov=Prov(input="src", file="loot_table/blocks/oak_log.json", ptr="p0e0"),
        )
    )
    return rule_set


def _result() -> SolveResult:
    return SolveResult(
        states={
            "item:minecraft:oak_planks": State.TRUE,
            "item:minecraft:oak_log": State.TRUE,
            "table:minecraft:blocks/oak_log": State.FALSE,
        },
        iterations=3,
        rules_true=1,
        rules_false=1,
    )


class RoundTripTest(unittest.TestCase):
    def test_rules_and_states_survive(self) -> None:
        original = _rules()
        result = _result()
        graph = serialize_graph(
            original,
            result,
            ["assume:player"],
            label="test",
            ir_schema=1,
            facts_digest={"loot": 1, "recipe": 1},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            write_graph(graph, path)
            back, states, header = read_graph(path)

        self.assertEqual([r.id for r in back.rules], [r.id for r in original.rules])
        for want, got in zip(original.rules, back.rules):
            self.assertEqual(got.head, want.head)
            self.assertEqual(got.body, want.body)
            self.assertEqual(got.soft, want.soft)
            self.assertEqual(got.kind, want.kind)
            self.assertEqual(got.family, want.family)
            self.assertEqual(got.meta, want.meta)
            self.assertEqual(got.prov, want.prov)

        self.assertIs(states.of("item:minecraft:oak_planks"), State.TRUE)
        self.assertIs(states.of("item:minecraft:oak_log"), State.TRUE)
        # 缺席的节点按 FALSE 处理，与 SolveResult.of 的语义一致
        self.assertIs(states.of("table:minecraft:blocks/oak_log"), State.FALSE)
        self.assertIs(states.of("item:minecraft:never_seen"), State.FALSE)

        self.assertEqual(header.label, "test")
        self.assertEqual(header.facts_digest, {"loot": 1, "recipe": 1})

    def test_write_is_byte_deterministic(self) -> None:
        """同一输入两次落盘必须逐字节相同，否则产物无法 diff。"""
        graph = serialize_graph(
            _rules(), _result(), ["assume:player"], label="t", ir_schema=1, facts_digest={}
        )
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.json"
            second = Path(tmp) / "b.json"
            write_graph(graph, first)
            write_graph(graph, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_strings_are_deduplicated(self) -> None:
        """同一字符串只在表里出现一次——这是体积的主要来源。"""
        graph = serialize_graph(
            _rules(), _result(), [], label="t", ir_schema=1, facts_digest={}
        )
        self.assertEqual(len(graph.strings), len(set(graph.strings)))
        # `item:minecraft:` 前缀的节点会被反复引用，去重后不该逐条内联
        self.assertIn("yield", graph.strings)


class FormatGuardTest(unittest.TestCase):
    def test_unknown_schema_is_refused(self) -> None:
        """更高版本直接失败：字段含义变了却强行解析会画出假路径。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            path.write_text(
                json.dumps(
                    {
                        "graph_schema": GRAPH_SCHEMA + 1,
                        "ir_schema": 1,
                        "label": "t",
                        "strings": [],
                        "rules": [],
                        "states": {"true": [], "unknown": {}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(GraphFormatError):
                read_graph(path)

    def test_missing_field_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            path.write_text(
                json.dumps({"graph_schema": GRAPH_SCHEMA, "ir_schema": 1}), encoding="utf-8"
            )
            with self.assertRaises(GraphFormatError):
                read_graph(path)

    def test_missing_file_has_a_usable_message(self) -> None:
        with self.assertRaises(GraphFormatError) as ctx:
            read_graph(Path("output/does_not_exist/graph.json"))
        self.assertIn("不存在", str(ctx.exception))

    def test_bad_string_index_is_refused(self) -> None:
        """下标越界必须报错，不能静默取到空串——那会让节点名变成 `""`。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            path.write_text(
                json.dumps(
                    {
                        "graph_schema": GRAPH_SCHEMA,
                        "ir_schema": 1,
                        "label": "t",
                        "strings": ["only"],
                        "rules": [[0, 99, [], [], 0, 0, 0, 0]],
                        "states": {"true": [], "unknown": {}},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(GraphFormatError):
                read_graph(path)


if __name__ == "__main__":
    unittest.main()
