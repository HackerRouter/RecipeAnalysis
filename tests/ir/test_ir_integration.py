"""IR 编译的集成测试：用真实输入包跑通「事实 → 规则 → 三值不动点」。

这里只钉住不变量，不钉可达率的绝对值——数字会随知识表演进，
钉死它只会让每次合理的改进都得改测试。要钉的是：

- **能编译**：任一版必须跑得完。1.18.2 曾在软约束里写 `state:`，
  而 `state` 不在固定集合内，整版直接抛 `NodeError`；
  26.3 因为走数据包表根本没走到那条路径，所以只有两版都跑才测得出来。
- **无未知**：红线 3 要求「未知全部有台账」，未知数必须为 0。
- **不复述结论**：可达率只断言下界，具体值由 `ra guide` 从产物读出
"""

from __future__ import annotations

import unittest

from ra.ir.compile import compile_ir
from ra.solve.fixpoint import State, solve

from .. import support


def _compile(label: str):
    store = support.store(label)
    rule_set, report = compile_ir(store, support.ROOT)
    return rule_set, report


def _universe(label: str) -> list[str]:
    """物品全集：取自 `registries.json`，与 `ra run` 同一条路径。

    **不能用规则里出现的节点**：没有规则的物品在规则图上不存在，
    拿它当全集会让这些物品从报告里消失。
    """
    from ra.facts import FactStore

    store = support.store(label)
    for fact in store.of_kind("registry"):
        if fact.payload.get("registry") == "minecraft:item":
            return sorted("item:" + name for name in fact.payload["entries"])
    return []


def _exceptions(universe: list[str]) -> dict:
    """例外表：与 `ra run` 同一条路径加载（含 `_patterns` 展开），避免测试与生产分叉。"""
    from ra.ir.knowledge import load_exceptions

    return load_exceptions(support.ROOT, universe)


def _item_rate(report) -> float:
    """物品可达率，分母即传入的全集。"""
    return report.rate


class _CompileBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        from ra.report import build_reachability

        cls.rules, cls.report = _compile(cls.label)
        cls.result = solve(cls.rules, cls.report.seeds)
        universe = _universe(cls.label)
        cls.reach = build_reachability(
            cls.rules,
            cls.result,
            identities=universe,
            exceptions=_exceptions(universe),
        )
        cls.attributions = cls.reach.attributions

    def test_every_rule_node_is_wellformed(self) -> None:
        """head / body / soft 全部要能 `split_node`。构造时已校验，这里再核一次。"""
        from ra.ir.nodes import split_node

        for rule in self.rules.rules:
            split_node(rule.head)
            for value in (*rule.body, *rule.soft):
                split_node(value)

    def test_rule_ids_are_unique(self) -> None:
        ids = [rule.id for rule in self.rules.rules]
        self.assertEqual(len(ids), len(set(ids)), "规则 id 必须全局唯一")

    def test_no_rule_has_head_in_body(self) -> None:
        for rule in self.rules.rules:
            self.assertNotIn(rule.head, rule.body, rule.id)

    def test_seeds_are_seeded(self) -> None:
        for seed in self.report.seeds:
            self.assertIs(self.result.of(seed), State.TRUE, seed)

    def test_unknown_is_empty(self) -> None:
        """M1：未知全部有台账。三值求解不得留下 UNKNOWN。"""
        self.assertEqual(self.result.counts().get("unknown", 0), 0)

    def test_unknown_serializers_is_empty(self) -> None:
        self.assertEqual(self.report.unknown_serializers, {})

    def test_shipped_knowledge_tables_are_actually_applied(self) -> None:
        """知识表必须真的接上：映射存在但一条规则都没产出，是静默失效。"""
        self.assertGreater(sum(self.report.rule_counts.values()), 1000)
        self.assertGreater(self.report.rule_counts.get("bridge/tag", 0), 0)
        self.assertGreater(self.report.rule_counts.get("bridge/table", 0), 0)
        self.assertGreater(self.report.rule_counts.get("bridge/convention", 0), 0)


@unittest.skipUnless(support.pack("26.3"), support.why("26.3"))
class Compile263Test(_CompileBase, unittest.TestCase):
    label = "26.3"

    def test_trades_family_is_wired(self) -> None:
        """交易族曾整体没实现，`filled_map` 这类只经交易可达的物品全线断。"""
        self.assertGreater(self.report.rule_counts.get("trades", 0), 300)

    def test_trade_sets_are_not_offers(self) -> None:
        """`layer=set` 的记录数应当与数据包里的 `trade_set` 文件数一致。"""
        self.assertEqual(self.report.trade_sets, 68)
        self.assertEqual(self.report.unresolved_trades, {})

    def test_transform_inverse_is_applied(self) -> None:
        """涂蜡与自然氧化都靠逆向规则；少了它们整片铜族不可达。"""
        inverses = [r for r in self.rules.rules if r.meta.get("inverse")]
        self.assertGreater(len(inverses), 0)

    def test_singleton_tools_are_bridged(self) -> None:
        self.assertIn("tool:minecraft:shears", self.result.states)
        self.assertIs(self.result.of("tool:minecraft:shears"), State.TRUE)

    def test_worldgen_tag_placement_is_expanded(self) -> None:
        self.assertTrue(
            any(r.head.startswith("tag:block/") for r in self.rules.rules),
            "世界生成里的 `#标签` 放置没有展开成成员方块",
        )

    def test_convention_coverage_is_complete(self) -> None:
        """约定必须报覆盖率；有配不上的条目就说明约定与注册表脱节。"""
        stats = self.report.convention_transforms
        for key, value in stats.items():
            if key.endswith(":miss"):
                self.assertEqual(value, 0, f"{key} 有配不上的方块")

    def test_template_blocks_are_bound(self) -> None:
        """模板里出现的方块必须接进获取链。

        只出现在结构里的方块（铜傀儡像、雕刻南瓜）没有世界生成引用也不会被
        放置桥接覆盖，`item ← table ← block` 整段悬空。
        """
        self.assertGreater(self.report.template_blocks, 300)
        self.assertGreater(self.report.rule_counts.get("bindings", 0), 300)
        self.assertEqual(self.report.unknown_template_blocks, {})

    def test_structure_spawns_are_bound(self) -> None:
        """结构的 `spawn_overrides` 是结构生物的唯一数据包来源。"""
        self.assertGreater(self.report.spawned_entities, 0)
        self.assertEqual(self.report.unknown_spawn_entities, {})

    def test_unobtainable_exceptions_are_reachable_in_report(self) -> None:
        """例外表里的物品应当归因为 unobtainable，而不是笼统的 no_rule。"""
        from ra.solve.attribute import UNOBTAINABLE

        reasons = {a.reason for a in self.attributions.values()}
        self.assertIn(UNOBTAINABLE, reasons)

    def test_reachability_meets_m1_floor(self) -> None:
        """26.3 可达率 ≥ 90%（分母见 ADR 0012）。只钉下界。"""
        self.assertGreaterEqual(_item_rate(self.reach), 0.90)

    def test_universe_is_registry_not_rule_nodes(self) -> None:
        """分母必须是 registries 全集，不能是「规则里出现的节点」。

        后者会让没有规则的物品从报告里消失，总数上少几个而看不出来。
        """
        from ra.facts import FactStore

        store = support.store(self.label)
        registry_count = 0
        for fact in store.of_kind("registry"):
            if fact.payload.get("registry") == "minecraft:item":
                registry_count = len(fact.payload["entries"])
                break
        self.assertGreater(registry_count, 0, "registries.json 缺 minecraft:item")
        self.assertEqual(sum(self.reach.counts.values()), registry_count)

    def test_cod_bucket_has_both_ways(self) -> None:
        """鳕鱼桶的两条途径：代码捞桶、渔夫交易。用来钉住「多途径」能力。

        只钉存在性（各一条），不钉谁先谁后——排序按 (body 长度, rule.id)，
        加规则会让顺序变，那是允许的。
        """
        from ra.solve.proof import enumerate_proofs

        by_head = {head: self.rules.of_head(head) for head in self.rules.heads()}
        steps = enumerate_proofs(by_head, self.result, "item:minecraft:cod_bucket")
        families = {step.rule.family for step in steps if step.rule}
        self.assertIn("code/mob_buckets", families)
        self.assertIn("trades", families)

    def test_why_resolves_bare_names(self) -> None:
        """`ra why` 接受裸名，这是命令行可用性的最低要求。"""
        from ra.cli import _resolve_node

        self.assertEqual(_resolve_node("cod_bucket"), "item:minecraft:cod_bucket")
        self.assertEqual(_resolve_node("minecraft:cod_bucket"), "item:minecraft:cod_bucket")
        self.assertEqual(
            _resolve_node("item:minecraft:cod_bucket"), "item:minecraft:cod_bucket"
        )
        self.assertEqual(_resolve_node("block:minecraft:stone"), "block:minecraft:stone")


@unittest.skipUnless(support.pack("1.18.2"), support.why("1.18.2"))
class Compile1182Test(_CompileBase, unittest.TestCase):
    label = "1.18.2"

    def test_reachability_meets_floor(self) -> None:
        """1.18.2 不是 M1 的验收对象，但掉到 80% 以下说明有族整体失灵。"""
        self.assertGreaterEqual(_item_rate(self.reach), 0.80)


class SolveTest(unittest.TestCase):
    """求解器本身的单元测试，不依赖输入包。"""

    def test_no_rule_and_not_seeded_is_false_not_unknown(self) -> None:
        from ra.ir.nodes import RuleSet

        result = solve(RuleSet(), ["assume:x"])
        self.assertIs(result.of("item:minecraft:air"), State.FALSE)

    def test_or_is_expressed_by_multiple_rules(self) -> None:
        from ra.ir.nodes import Rule, RuleSet

        rule_set = RuleSet()
        rule_set.extend(
            [
                Rule(id="a", head="item:minecraft:x", body=("assume:x",)),
                Rule(id="b", head="item:minecraft:x", body=("item:minecraft:y",)),
            ]
        )
        result = solve(rule_set, ["assume:x", "item:minecraft:y"])
        self.assertIs(result.of("item:minecraft:x"), State.TRUE)

    def test_and_requires_every_body_member(self) -> None:
        from ra.ir.nodes import Rule, RuleSet

        rule_set = RuleSet()
        rule_set.extend(
            [
                Rule(id="a", head="item:minecraft:x", body=("assume:x", "item:minecraft:y")),
            ]
        )
        result = solve(rule_set, ["assume:x"])
        self.assertIs(result.of("item:minecraft:x"), State.FALSE)

    def test_cycle_without_entry_stays_false(self) -> None:
        from ra.ir.nodes import Rule, RuleSet

        rule_set = RuleSet()
        rule_set.extend(
            [
                Rule(id="a", head="item:minecraft:x", body=("item:minecraft:y",)),
                Rule(id="b", head="item:minecraft:y", body=("item:minecraft:x",)),
            ]
        )
        result = solve(rule_set, [])
        self.assertIs(result.of("item:minecraft:x"), State.FALSE)
        self.assertIs(result.of("item:minecraft:y"), State.FALSE)


if __name__ == "__main__":
    unittest.main()
