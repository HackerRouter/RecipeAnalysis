"""黄金样本测试：已知答案，跨版本。

断言全部基于 `tests/golden.py` 的声明。加物品就加一条 `Sample`，不在这里写逻辑。
"""

from __future__ import annotations

import unittest

from ra.report import build_reachability
from ra.solve.fixpoint import State

from .. import support
from ..golden import ALL_SAMPLES, Sample

_CACHE: dict[str, tuple] = {}


def _solve(label: str):
    """版本级缓存：编译一次、求解一次，样本之间共享。"""
    if label in _CACHE:
        return _CACHE[label]

    from ra.ir.knowledge import load_exceptions
    from ra.ir.compile import compile_ir
    from ra.solve.fixpoint import solve

    store = support.store(label)
    rules, report = compile_ir(store, support.ROOT)
    result = solve(rules, report.seeds)
    reach = build_reachability(rules, result, exceptions=load_exceptions(support.ROOT))
    by_head = {head: rules.of_head(head) for head in rules.heads()}
    _CACHE[label] = (rules, result, reach, by_head)
    return _CACHE[label]


class _GoldenBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        # 注意：不要把模块级函数存成类属性——通过实例访问会绑定 `self`，
        # 调用时凭空多出一个位置参数。
        cls.rules, cls.result, cls.reach, cls.by_head = _solve(cls.label)

    def samples(self) -> tuple[Sample, ...]:
        return ALL_SAMPLES[self.label]

    def _live_rules(self, node: str) -> list:
        """该节点上 body 全为 TRUE 的规则。

        这就是「能用哪些方式拿到它」的直接答案。
        """
        return [
            rule
            for rule in self.by_head.get(node, [])
            if all(self.result.of(target) is State.TRUE for target in rule.body)
        ]

    def _reachable_graph(self, node: str) -> tuple[set[str], set[str]]:
        """从该节点出发、只走 body 全 TRUE 的规则所能到达的全部族与节点。

        为什么走子图而不是只看顶层规则：**变换族给的是 `block:` 上的规则**。
        `red_concrete` 的顶层只有一条 `loot`，它的「粉末遇水固化」在
        `block:minecraft:red_concrete` 上；只看顶层会判成「没有约定变换」。

        也不走证明树：`enumerate_proofs` 每个中间节点只展开有限条子路径，
        同样会漏。这里按可达性而不是按展开预算收集。
        """
        families: set[str] = set()
        nodes: set[str] = set()
        stack = [node]
        while stack:
            current = stack.pop()
            if current in nodes:
                continue
            nodes.add(current)
            for rule in self._live_rules(current):
                families.add(rule.family)
                stack.extend(rule.body)
                stack.extend(rule.soft)
        return families, nodes

    def _families_at(self, node: str) -> set[str]:
        return self._reachable_graph(node)[0]

    def _tree_nodes(self, node: str) -> set[str]:
        return self._reachable_graph(node)[1]

    def test_status_matches(self) -> None:
        for sample in self.samples():
            with self.subTest(node=sample.node, covers=sample.covers):
                state = self.result.of(sample.node)
                expected = State.TRUE if sample.status == "true" else State.FALSE
                self.assertIs(state, expected, f"{sample.node}：{sample.note}")

    def test_reason_matches(self) -> None:
        for sample in self.samples():
            if sample.status == "true" or not sample.reason:
                continue
            with self.subTest(node=sample.node):
                attribution = self.reach.attributions.get(sample.node)
                self.assertIsNotNone(attribution, f"{sample.node} 没有归因记录")
                self.assertEqual(
                    attribution.reason, sample.reason, f"{sample.node}：{sample.note}"
                )

    def test_families_present(self) -> None:
        for sample in self.samples():
            if not sample.family:
                continue
            with self.subTest(node=sample.node):
                families = self._families_at(sample.node)
                for wanted in sample.family:
                    self.assertTrue(
                        any(f.startswith(wanted) for f in families),
                        f"{sample.node} 没有可用的 {wanted} 途径，实际 {sorted(families)}",
                    )

    def test_families_absent(self) -> None:
        """没有任何样本填 `absent_family` 时，本测试恒真（见 `golden.Sample` 的注）。"""
        for sample in self.samples():
            if not sample.absent_family:
                continue
            with self.subTest(node=sample.node):
                families = self._families_at(sample.node)
                for banned in sample.absent_family:
                    self.assertFalse(
                        any(f.startswith(banned) for f in families),
                        f"{sample.node} 不该经 {banned} 拿到，实际 {sorted(families)}",
                    )

    def test_nodes_present(self) -> None:
        for sample in self.samples():
            if not sample.node_contains:
                continue
            with self.subTest(node=sample.node):
                nodes = self._tree_nodes(sample.node)
                for wanted in sample.node_contains:
                    self.assertIn(wanted, nodes, sample.note)

    def test_missing_matches(self) -> None:
        """没有样本填 `missing_any` 时本测试恒真；26.3 目前就是这种情况。"""
        for sample in self.samples():
            if not sample.missing_any:
                continue
            with self.subTest(node=sample.node):
                attribution = self.reach.attributions.get(sample.node)
                self.assertIsNotNone(attribution)
                self.assertTrue(
                    set(attribution.missing) & set(sample.missing_any),
                    f"{sample.node} 缺项实际 {attribution.missing}",
                )

    def test_cycle_matches(self) -> None:
        """没有样本填 `cycle_any` 时本测试恒真；26.3 目前就是这种情况。"""
        for sample in self.samples():
            if not sample.cycle_any:
                continue
            with self.subTest(node=sample.node):
                attribution = self.reach.attributions.get(sample.node)
                self.assertIsNotNone(attribution)
                self.assertTrue(
                    set(attribution.cycle) & set(sample.cycle_any),
                    f"{sample.node} 环实际 {attribution.cycle}",
                )

    def test_alternatives_floor(self) -> None:
        for sample in self.samples():
            if not sample.min_alternatives:
                continue
            with self.subTest(node=sample.node):
                rules = self.rules.of_head(sample.node)
                self.assertGreaterEqual(
                    len(rules), sample.min_alternatives, f"{sample.node}：{sample.note}"
                )


@unittest.skipUnless(support.pack("26.3"), support.why("26.3"))
class Golden263Test(_GoldenBase, unittest.TestCase):
    label = "26.3"


@unittest.skipUnless(support.pack("1.18.2"), support.why("1.18.2"))
class Golden1182Test(_GoldenBase, unittest.TestCase):
    label = "1.18.2"


class GoldenCoverageTest(unittest.TestCase):
    """样本表本身要覆盖下面 `REQUIRED` 列举的每一类。"""

    # 清单，一项不能少
    REQUIRED = (
        "双路径",
        "机制搬家",
        "别名",
        "代码承载",
        "工具门槛",
        "变体",
        "未知依赖",
        "无来源",
        "循环无入口",
        "模板承载",
        "实体行为",
        "实体来源",
        "交互来源",
    )

    def test_required_kinds_are_covered(self) -> None:
        covered = {sample.covers for samples in ALL_SAMPLES.values() for sample in samples}
        missing = [kind for kind in self.REQUIRED if kind not in covered]
        self.assertEqual(missing, [], f"黄金样本缺这些类：{missing}")

    def test_every_sample_has_a_reason_or_note(self) -> None:
        for label, samples in ALL_SAMPLES.items():
            for sample in samples:
                self.assertTrue(
                    sample.note or sample.reason,
                    f"{label} {sample.node} 既没有说明也没有归因",
                )

    def test_both_versions_have_samples(self) -> None:
        """每份输入包都要有样本；样本表里也不许留已删版本的条目。

        版本清单取自 `support.known_labels()`（扫描 `inputs/*/`），不硬编码：
        加版本时只要放输入包并补样本，这条断言立刻要求补齐；漏补则失败。
        硬编码 `("26.3", "1.18.2")` 时，新版本缺样本也无人报错。
        """
        known = set(support.known_labels())
        if not known:
            self.skipTest("没有输入包，无从核对版本清单")

        missing = sorted(known - set(ALL_SAMPLES))
        self.assertEqual(missing, [], f"这些版本没有黄金样本：{missing}")
        stale = sorted(set(ALL_SAMPLES) - known)
        self.assertEqual(stale, [], f"样本表里有不存在的版本：{stale}")
        for label in sorted(known):
            self.assertGreater(len(ALL_SAMPLES[label]), 0, f"{label} 的样本是空的")


if __name__ == "__main__":
    unittest.main()
