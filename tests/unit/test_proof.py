"""证明枚举的单元测试：不依赖输入包。

`oa why` 的回答质量全靠这一层：它要说清「有哪几条拿法」，而不只是「能拿到」。
"""

from __future__ import annotations

import unittest

from oa.ir.nodes import Rule, RuleSet
from oa.solve.fixpoint import State, solve
from oa.solve.proof import enumerate_proofs, flatten_leaves, iter_steps


def _setup(rules: list[Rule], seeds: list[str]):
    rule_set = RuleSet()
    rule_set.extend(rules)
    result = solve(rule_set, seeds)
    by_head = {head: rule_set.of_head(head) for head in rule_set.heads()}
    return by_head, result


class EnumerateTest(unittest.TestCase):
    def test_two_ways_are_both_reported(self) -> None:
        """两条独立来源都要出现——这正是 `proofs`（单条）给不了的。"""
        by_head, result = _setup(
            [
                Rule(id="a", head="item:minecraft:x", body=("assume:one",)),
                Rule(id="b", head="item:minecraft:x", body=("assume:two",)),
            ],
            ["assume:one", "assume:two"],
        )
        steps = enumerate_proofs(by_head, result, "item:minecraft:x")
        self.assertEqual(len(steps), 2)
        leaves = {tuple(s.node for s in flatten_leaves(step)) for step in steps}
        self.assertEqual(leaves, {("assume:one",), ("assume:two",)})

    def test_dead_rule_is_not_a_path(self) -> None:
        """body 不全为真的规则不是途径，不能出现在输出里。"""
        by_head, result = _setup(
            [
                Rule(id="a", head="item:minecraft:x", body=("assume:one",)),
                Rule(id="b", head="item:minecraft:x", body=("item:minecraft:nowhere",)),
            ],
            ["assume:one"],
        )
        steps = enumerate_proofs(by_head, result, "item:minecraft:x")
        self.assertEqual([s.rule.id for s in steps], ["a"])

    def test_false_node_has_no_paths(self) -> None:
        by_head, result = _setup(
            [Rule(id="a", head="item:minecraft:x", body=("assume:absent",))], []
        )
        self.assertEqual(result.of("item:minecraft:x"), State.FALSE)
        self.assertEqual(enumerate_proofs(by_head, result, "item:minecraft:x"), [])

    def test_and_body_expands_all_prerequisites(self) -> None:
        by_head, result = _setup(
            [
                Rule(id="a", head="item:minecraft:x", body=("assume:one", "assume:two")),
            ],
            ["assume:one", "assume:two"],
        )
        steps = enumerate_proofs(by_head, result, "item:minecraft:x")
        self.assertEqual(len(steps), 1)
        self.assertEqual({s.node for s in steps[0].children}, {"assume:one", "assume:two"})

    def test_unexpanded_alternatives_are_reported(self) -> None:
        """中间节点有多条来源却只展开一条时，必须报出还有几条。

        不报就等于暗示「只有这一条」——用户看到绿宝石只来自沙漠金字塔会误判。
        """
        by_head, result = _setup(
            [
                Rule(id="a", head="item:minecraft:x", body=("item:minecraft:y",)),
                Rule(id="y1", head="item:minecraft:y", body=("assume:one",)),
                Rule(id="y2", head="item:minecraft:y", body=("assume:two",)),
                Rule(id="y3", head="item:minecraft:y", body=("assume:three",)),
            ],
            ["assume:one", "assume:two", "assume:three"],
        )
        steps = enumerate_proofs(by_head, result, "item:minecraft:x", branch_limit=1)
        self.assertEqual(len(steps), 1)
        self.assertTrue(
            any("item:minecraft:y" in note and "2" in note for note in steps[0].unexpanded),
            steps[0].unexpanded,
        )

    def test_branch_limit_widens_the_tree(self) -> None:
        by_head, result = _setup(
            [
                Rule(id="a", head="item:minecraft:x", body=("item:minecraft:y",)),
                Rule(id="y1", head="item:minecraft:y", body=("assume:one",)),
                Rule(id="y2", head="item:minecraft:y", body=("assume:two",)),
            ],
            ["assume:one", "assume:two"],
        )
        steps = enumerate_proofs(by_head, result, "item:minecraft:x", branch_limit=2)
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(steps[0].children), 2)
        self.assertEqual(steps[0].unexpanded, [])

    def test_cycle_is_cut_not_looped(self) -> None:
        """环必须截断。能走到这里说明有入口，环只是路径上的一条支线。"""
        by_head, result = _setup(
            [
                Rule(id="a", head="item:minecraft:x", body=("item:minecraft:y",)),
                Rule(id="b", head="item:minecraft:y", body=("item:minecraft:x", "assume:one")),
            ],
            ["assume:one", "item:minecraft:x"],
        )
        steps = enumerate_proofs(by_head, result, "item:minecraft:x")
        self.assertEqual(len(steps), 1)
        # 截断发生在 y 的子层：x 已经在这条路径上出现过
        cut_nodes = [s.node for s in iter_steps(steps[0]) if s.cut]
        self.assertEqual(cut_nodes, ["item:minecraft:x"])

    def test_max_depth_cuts(self) -> None:
        rules = [
            Rule(id=f"r{i}", head=f"item:minecraft:n{i}", body=(f"item:minecraft:n{i + 1}",))
            for i in range(6)
        ]
        rules.append(Rule(id="end", head="item:minecraft:n6", body=("assume:x",)))
        by_head, result = _setup(rules, ["assume:x"])
        steps = enumerate_proofs(by_head, result, "item:minecraft:n0", max_depth=3)
        self.assertEqual(len(steps), 1)
        self.assertTrue(any(s.cut for s in iter_steps(steps[0])))

    def test_seeds_are_rendered_as_roots(self) -> None:
        """`assume:` / `world:` 是分析起点，不再往上追问。"""
        by_head, result = _setup(
            [Rule(id="a", head="item:minecraft:x", body=("world:minecraft:overworld",))],
            ["world:minecraft:overworld"],
        )
        step = enumerate_proofs(by_head, result, "item:minecraft:x")[0]
        self.assertTrue(step.children[0].is_root)


if __name__ == "__main__":
    unittest.main()
