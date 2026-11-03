"""建图逻辑：剪枝、聚合、折叠与「走不通」标注。

这些测试不启 Graphviz，只调 `build_path_graph` 与渲染前的图结构。
判据比外观重要——外观会调，判据不该动。
"""

from __future__ import annotations

import unittest

from oa.facts.schema import Prov
from oa.ir.nodes import Rule, RuleSet
from oa.report.paths import PathBuildError, PathOptions, build_path_graph
from oa.report.paths.render import build_dot
from oa.report.paths.style import TARGET_BORDER, TARGET_FILL, condition_label, craft_of
from oa.solve.fixpoint import SolveResult, State


def _rule(rid: str, head: str, body: tuple[str, ...], *, family: str = "recipes", **meta) -> Rule:
    return Rule(
        id=rid,
        head=head,
        body=body,
        kind="yield",
        family=family,
        meta=meta,
        prov=Prov(input="src", file=f"{rid}.json"),
    )


def _world(*nodes: str, rules: list[Rule] | None = None) -> tuple[RuleSet, SolveResult]:
    """把 `nodes` 全部判 TRUE 的规则集。规则可另给。"""
    rule_set = RuleSet()
    for rule in rules or []:
        rule_set.add(rule)
    result = SolveResult(states={node: State.TRUE for node in nodes})
    return rule_set, result


class BuildTest(unittest.TestCase):
    def test_only_true_rules_are_drawn(self) -> None:
        """body 含 FALSE 的规则不画边——图上每条边都能追到根。"""
        rules = [
            _rule("live", "item:minecraft:plank", ("tag:item/logs",)),
            _rule("dead", "item:minecraft:plank", ("table:minecraft:blocks/nowhere",)),
        ]
        rule_set, result = _world("item:minecraft:plank", "tag:item/logs", rules=rules)
        built = build_path_graph(rule_set, result, "item:minecraft:plank", PathOptions(depth=2))

        self.assertNotIn("table:minecraft:blocks/nowhere", built.graph.nodes)
        self.assertIn("tag:item/logs", built.graph.nodes)

    def test_blocked_rules_are_reported_not_dropped(self) -> None:
        """走不通的规则不画边，但必须报数。

        只画 TRUE 的那部分时，读者会把「画出来的这些」当成全部途径。
        便签只报数与主要缺项，明细进 tooltip。
        """
        rules = [
            _rule("live", "item:minecraft:plank", ("tag:item/logs",)),
            _rule("dead", "item:minecraft:plank", ("table:minecraft:blocks/nowhere",)),
            _rule("dead2", "item:minecraft:plank", ("entity:minecraft:no_mob",)),
        ]
        rule_set, result = _world("item:minecraft:plank", "tag:item/logs", rules=rules)
        built = build_path_graph(rule_set, result, "item:minecraft:plank", PathOptions(depth=2))

        self.assertEqual(built.graph.blocked.get("item:minecraft:plank"), 2)
        note = built.graph.nodes.get("blocked::item:minecraft:plank")
        self.assertIsNotNone(note, "走不通的途径没有留痕")
        self.assertIn("2 条走不通", note["label"])
        self.assertIn("nowhere", note["tooltip"])

    def test_blocked_note_is_dashed(self) -> None:
        """便签不是来源，边必须是虚线且无箭头。"""
        rules = [
            _rule("live", "item:minecraft:plank", ("tag:item/logs",)),
            _rule("dead", "item:minecraft:plank", ("table:minecraft:blocks/nowhere",)),
        ]
        rule_set, result = _world("item:minecraft:plank", "tag:item/logs", rules=rules)
        built = build_path_graph(rule_set, result, "item:minecraft:plank", PathOptions(depth=2))
        key = ("blocked::item:minecraft:plank", "item:minecraft:plank", "blocked::item:minecraft:plank")
        self.assertIn(key, built.graph.dashed)

    def test_single_predecessor_is_merged_into_an_edge(self) -> None:
        """单前件且无条件的规则不画菱形：一条挖矿链不该是三段菱形。"""
        rules = [_rule("a", "item:minecraft:plank", ("tag:item/logs",))]
        rule_set, result = _world("item:minecraft:plank", "tag:item/logs", rules=rules)
        built = build_path_graph(rule_set, result, "item:minecraft:plank", PathOptions(depth=2))

        self.assertIn("a", built.graph.merged)
        self.assertEqual(len(built.graph.rules), 0)

    def test_conditions_stay_in_the_diamond(self) -> None:
        """带条件的规则保留菱形，条件写进标签。

        压成边就只能把条件塞进箭头标签，一长串没法读，
        也失去「这条规则的前提是一个整体」这个结构。
        """
        rules = [
            _rule(
                "mine",
                "item:minecraft:emerald",
                ("table:minecraft:blocks/emerald_ore", "tool:minecraft:iron_pickaxe"),
                family="loot",
                table="minecraft:blocks/emerald_ore",
            )
        ]
        rule_set, result = _world(
            "item:minecraft:emerald",
            "table:minecraft:blocks/emerald_ore",
            "tool:minecraft:iron_pickaxe",
            rules=rules,
        )
        built = build_path_graph(rule_set, result, "item:minecraft:emerald", PathOptions(depth=2))

        self.assertEqual(len(built.graph.rules), 1)
        label = built.graph.nodes["rule::mine"]["label"]
        self.assertIn("工具", label)
        self.assertIn("铁镐", label)

    def test_unknown_target_raises(self) -> None:
        rule_set, result = _world("item:minecraft:plank")
        with self.assertRaises(PathBuildError):
            build_path_graph(rule_set, result, "item:minecraft:not_a_thing", PathOptions())

    def test_depth_cut_is_marked(self) -> None:
        """到深度上限的节点画成虚线 cut，而不是静默消失。"""
        rules = [_rule("a", "item:minecraft:b", ("tag:item:t",))]
        rule_set, result = _world("item:minecraft:b", "tag:item:t", rules=rules)
        built = build_path_graph(rule_set, result, "item:minecraft:b", PathOptions(depth=1))
        self.assertTrue(built.graph.nodes["tag:item:t"].get("cut"))


class OptionsTest(unittest.TestCase):
    def test_invalid_rankdir_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            PathOptions(rankdir="UP")

    def test_depth_must_allow_at_least_one_level(self) -> None:
        with self.assertRaises(ValueError):
            PathOptions(depth=0)

    def test_zero_means_disabled_for_merge(self) -> None:
        """0 是「关闭」，负数是错误——两者不能混。"""
        self.assertEqual(PathOptions(merge_isomorphic=0).merge_isomorphic, 0)
        with self.assertRaises(ValueError):
            PathOptions(merge_isomorphic=-1)


class DescribeTest(unittest.TestCase):
    """参数说明：原始命令行形式，全量，不做任何翻译。"""

    def test_every_flag_appears(self) -> None:
        """一个参数都不许漏：漏掉的那个读者会当成默认值。"""
        text = "\n".join(PathOptions().describe())
        flags = (
            "--depth", "--branches", "--max-nodes", "--max-groups",
            "--group-min", "--merge-isomorphic", "--merge-leaves",
            "--expand-tags", "--expand-conditions", "--expand-groups",
            "--keep-tables", "--keep-roots", "--rankdir",
        )
        for flag in flags:
            self.assertIn(flag, text, f"{flag} 没写进参数说明")

    def test_values_are_raw_not_translated(self) -> None:
        """值必须是原样，不译成「开 / 关」。

        译文只存在于展示层，查不到定义；原文则永远与 `build_parser` 一致。
        """
        text = "\n".join(PathOptions().describe())
        self.assertIn("--expand-tags False", text)
        self.assertIn("--merge-isomorphic 0", text)
        self.assertNotIn("=关", text)
        self.assertNotIn("关", text)

    def test_defaults_are_shown_not_omitted(self) -> None:
        """默认值也要写。

        图会脱离命令行单独传阅。只写「与默认值的差」，读者就无法判断
        `--depth 4` 是特意调的还是没动过——两种情况下结论的适用范围不同。
        """
        text = "\n".join(PathOptions().describe())
        self.assertIn("--depth 4", text)
        self.assertIn("--branches 4", text)
        self.assertIn("--max-nodes 500", text)
        self.assertIn("--rankdir TB", text)

    def test_non_default_values_show_up(self) -> None:
        options = PathOptions(
            merge_isomorphic=3, merge_leaves=2, expand_tags=True, rankdir="LR"
        )
        text = "\n".join(options.describe())
        self.assertIn("--merge-isomorphic 3", text)
        self.assertIn("--merge-leaves 2", text)
        self.assertIn("--expand-tags True", text)
        self.assertIn("--rankdir LR", text)

    def test_one_flag_per_line(self) -> None:
        """一项一行：HTML 侧靠它排版，拼成一行就分不清谁配谁。"""
        for line in PathOptions().describe():
            self.assertEqual(line.count("--"), 1, f"{line!r} 里不止一个参数")
            self.assertTrue(line.startswith("--"), f"{line!r} 不是 flag 起始")


class NoCaptionTest(unittest.TestCase):
    """参数只写 HTML 文字区，不进图内标题。

    图内标题在放大的图里会跟着缩成一条细线，而它恰恰最需要看清。
    """

    def test_dot_has_no_graph_label(self) -> None:
        rule_set, result = _world("item:minecraft:x")
        options = PathOptions(merge_isomorphic=3)
        built = build_path_graph(rule_set, result, "item:minecraft:x", options)
        dot = build_dot(built.graph, options)
        self.assertNotIn("labelloc", dot)
        self.assertNotIn("--merge-isomorphic", dot)
        for line in dot.splitlines():
            self.assertFalse(
                line.strip().startswith("label="), f"DOT 里有图级 label：{line}"
            )


class AbsorbRootsTest(unittest.TestCase):
    """全局起点的边收进产物标签，不画成从一个椭圆射出的星形。"""

    def _seeded(self, body: str) -> tuple[RuleSet, SolveResult]:
        """`block:X ← seeds ← body` 的单前件规则。"""
        rule = _rule(
            "seed",
            "block:minecraft:x",
            (body,),
            family="worldgen",
            worldgen_kind="feature",
        )
        return _world("block:minecraft:x", body, rules=[rule])

    def test_world_edge_becomes_a_label_line(self) -> None:
        rule_set, result = self._seeded("world:minecraft:overworld")
        built = build_path_graph(rule_set, result, "block:minecraft:x", PathOptions(depth=2))

        self.assertNotIn("world:minecraft:overworld", built.graph.nodes, "起点节点应被吸收")
        self.assertEqual(
            built.graph.nodes["block:minecraft:x"]["origin"], "主世界生成"
        )
        self.assertIn("主世界生成", built.graph.nodes["block:minecraft:x"]["label"])
        self.assertEqual(built.absorbed_roots, 1)

    def test_structure_placement_carries_the_structure_name(self) -> None:
        """`结构放置·village`：结构名进标签，但**保持原名**。

        结构清单随版本增减，译名表必然不全；不全就变成中英混排
        （`玩法 · cat_morning_gift · 试炼密室`），读者还得猜哪个是原名。
        原名还能直接对照数据包路径查证。
        """
        rule = _rule(
            "tpl",
            "block:minecraft:x",
            ("world:minecraft:overworld",),
            family="bindings/template_block",
            templates=["data/minecraft/structure/village/plains/houses/x.snbt"],
        )
        rule_set, result = _world(
            "block:minecraft:x", "world:minecraft:overworld", rules=[rule]
        )
        built = build_path_graph(rule_set, result, "block:minecraft:x", PathOptions(depth=2))

        self.assertIn("结构放置·village", built.graph.nodes["block:minecraft:x"]["origin"])

    def test_generation_never_carries_a_structure_name(self) -> None:
        """世界生成不是某个结构给的，标签里不该出现模板首段。"""
        rule = _rule(
            "seed",
            "block:minecraft:x",
            ("world:minecraft:overworld",),
            family="worldgen",
            templates=["data/minecraft/structure/village/plains/houses/x.snbt"],
        )
        rule_set, result = _world(
            "block:minecraft:x", "world:minecraft:overworld", rules=[rule]
        )
        built = build_path_graph(rule_set, result, "block:minecraft:x", PathOptions(depth=2))
        self.assertEqual(built.graph.nodes["block:minecraft:x"]["origin"], "主世界生成")

    def test_keep_roots_leaves_the_graph_alone(self) -> None:
        rule_set, result = self._seeded("world:minecraft:overworld")
        built = build_path_graph(
            rule_set,
            result,
            "block:minecraft:x",
            PathOptions(depth=2, keep_roots=True),
        )
        self.assertIn("world:minecraft:overworld", built.graph.nodes)
        self.assertEqual(built.absorbed_roots, 0)

    def test_root_edge_into_a_diamond_is_not_absorbed(self) -> None:
        """交易是 AND：假设 + 付款物缺一不可，删掉假设会让整条规则失效。"""
        rule = _rule(
            "trade",
            "item:minecraft:boots",
            ("assume:villager_trade", "item:minecraft:emerald"),
            family="trades",
            profession="armorer",
        )
        rule_set, result = _world(
            "item:minecraft:boots",
            "assume:villager_trade",
            "item:minecraft:emerald",
            rules=[rule],
        )
        built = build_path_graph(
            rule_set, result, "item:minecraft:boots", PathOptions(depth=2)
        )

        self.assertIn("assume:villager_trade", built.graph.nodes, "AND 成员不能被吸收")
        self.assertIn("rule::trade", built.graph.nodes)
        self.assertEqual(built.absorbed_roots, 0)

    def test_repeated_origin_is_written_once(self) -> None:
        """同一个起点有多条规则时（生成有 7 条），标签里只写一次。"""
        rules = [
            _rule(f"seed{n}", "block:minecraft:x", ("world:minecraft:overworld",),
                  family="worldgen", worldgen_kind="feature")
            for n in range(4)
        ]
        rule_set, result = _world(
            "block:minecraft:x", "world:minecraft:overworld", rules=rules
        )
        built = build_path_graph(
            rule_set,
            result,
            "block:minecraft:x",
            PathOptions(depth=2, expand_groups=True, group_min=1),
        )
        self.assertEqual(built.graph.nodes["block:minecraft:x"]["origin"], "主世界生成")


class OrphanTableTest(unittest.TestCase):
    """深度截断会留下「没有入边」的战利品表。

    表节点建出来了，但它的来源没画，于是成了悬空椭圆。它不是来源，
    而是「从哪拿」，该收进产物标签，而不是在图上凭空占一个位置。
    """

    def test_orphan_table_is_written_into_the_product_label(self) -> None:
        rules = [
            _rule(
                "chest",
                "item:minecraft:emerald",
                ("table:minecraft:chests/trial_chambers/intersection",),
                family="loot",
                table="minecraft:chests/trial_chambers/intersection",
            )
        ]
        rule_set, result = _world(
            "item:minecraft:emerald",
            "table:minecraft:chests/trial_chambers/intersection",
            "assume:structure_loot",
            rules=rules,
        )
        # depth=1：产物的一级来源画出来，表的上游不画，表于是没有入边
        built = build_path_graph(
            rule_set, result, "item:minecraft:emerald", PathOptions(depth=1)
        )

        self.assertNotIn(
            "table:minecraft:chests/trial_chambers/intersection", built.graph.nodes
        )
        self.assertIn(
            "宝箱 · trial_chambers/intersection",
            built.graph.nodes["item:minecraft:emerald"]["origin"],
        )

    def test_orphan_table_into_a_diamond_is_kept(self) -> None:
        """指向菱形时不能吸：菱形是 AND 的一员，失去表名就说不清是什么规则。"""
        rules = [
            _rule(
                "mine",
                "item:minecraft:emerald",
                (
                    "table:minecraft:blocks/emerald_ore",
                    "tool:minecraft:iron_pickaxe",
                ),
                family="loot",
                table="minecraft:blocks/emerald_ore",
            )
        ]
        rule_set, result = _world(
            "item:minecraft:emerald",
            "table:minecraft:blocks/emerald_ore",
            "tool:minecraft:iron_pickaxe",
            rules=rules,
        )
        built = build_path_graph(
            rule_set, result, "item:minecraft:emerald", PathOptions(depth=2)
        )
        self.assertIn("table:minecraft:blocks/emerald_ore", built.graph.nodes)


class CollapseTablesTest(unittest.TestCase):
    def test_two_tables_onto_one_product_do_not_overwrite(self) -> None:
        """试炼密室的交叉口箱、奖励箱都出绿宝石块，两个表名都要留下。

        压出来的边曾经共用 `(来源, 产物, tag)` 这个 key，后压的会覆盖先压的。
        """
        tables = [
            "table:minecraft:chests/trial_chambers/intersection",
            "table:minecraft:chests/trial_chambers/reward_ominous_rare",
        ]
        rules = [
            _rule(f"c{n}", "item:minecraft:emerald_block", (table,), family="loot",
                  table=table.split(":", 1)[1])
            for n, table in enumerate(tables)
        ] + [
            _rule(f"t{n}", table, ("assume:structure_loot",), family="bridge")
            for n, table in enumerate(tables)
        ]
        rule_set, result = _world(
            "item:minecraft:emerald_block", "assume:structure_loot", *tables,
            rules=rules,
        )
        built = build_path_graph(
            rule_set, result, "item:minecraft:emerald_block", PathOptions(depth=4)
        )

        origin = built.graph.nodes["item:minecraft:emerald_block"]["origin"]
        self.assertIn("trial_chambers/intersection", origin)
        self.assertIn("trial_chambers/reward_ominous_rare", origin)


class IsomorphicUnderBudgetTest(unittest.TestCase):
    """`--merge-isomorphic` 与 `--branches` 不能互相压制。

    默认 `--branches 4` 会把 13 种木台阶只铺开 4 种。折叠判据若只数
    「已在图上」的成员，永远过不了「多数」这条线，同构折叠等于没开——
    用户开了参数却看不到任何变化。

    修法是把被预算挡住的成员算进判断（`PathGraph.suppressed`），
    但**不能**因此放宽到「有 2 个成员就折」：从单个台阶出发时，
    上级 `tag:item/slabs`（96 组）只有 1 个成员在图里，折它会画出
    本层不该出现的边。
    """

    # 13 种木头，对应 `wooden_slabs` 的成员（26.3 实测就是 13 种）
    WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove",
             "cherry", "pale_oak", "bamboo", "crimson", "warped", "bamboo_mosaic")

    def _chain(self) -> tuple[RuleSet, SolveResult]:
        """13 个 `item:X_slab ← 木板 ← tag:logs`，外加制品 `item:lectern`。

        两级 tag 必须都在：台阶的来源 tag 是 `tag:item/planks`（13 个成员），
        只建 `tag:X_logs` 的话同构簇的「来源归一」那一步找不到覆盖多个成员的 tag。
        """
        rules = [
            _rule(
                f"slab_{wood}",
                f"item:minecraft:{wood}_slab",
                (f"item:minecraft:{wood}_planks", "station:minecraft:crafting_table"),
                family="recipes",
                serializer="minecraft:crafting_shaped",
            )
            for wood in self.WOODS
        ] + [
            _rule(
                f"planks_{wood}",
                f"item:minecraft:{wood}_planks",
                (f"tag:item/minecraft:{wood}_logs",),
                family="recipes",
                serializer="minecraft:crafting_shaped",
            )
            for wood in self.WOODS
        ] + [
            _rule(
                "lectern",
                "item:minecraft:lectern",
                ("tag:item/minecraft:wooden_slabs", "station:minecraft:crafting_table"),
                family="recipes",
                serializer="minecraft:crafting_shaped",
            )
        ]
        members = [
            _rule(f"m_{wood}", "tag:item/minecraft:wooden_slabs",
                  (f"item:minecraft:{wood}_slab",), family="bridge/tag")
            for wood in self.WOODS
        ] + [
            _rule(f"p_{wood}", "tag:item/minecraft:planks",
                  (f"item:minecraft:{wood}_planks",), family="bridge/tag")
            for wood in self.WOODS
        ]
        nodes = [
            *(f"item:minecraft:{w}_slab" for w in self.WOODS),
            *(f"item:minecraft:{w}_planks" for w in self.WOODS),
            *(f"tag:item/minecraft:{w}_logs" for w in self.WOODS),
            "item:minecraft:lectern",
            "tag:item/minecraft:wooden_slabs",
            "tag:item/minecraft:planks",
            "station:minecraft:crafting_table",
        ]
        return _world(*nodes, rules=rules + members)

    def test_folding_works_even_when_branches_is_small(self) -> None:
        """`--branches 4` 只铺开 4 个成员，折叠仍应发生。"""
        rule_set, result = self._chain()
        built = build_path_graph(
            rule_set,
            result,
            "item:minecraft:lectern",
            PathOptions(
                depth=4,
                expand_tags=True,
                expand_groups=True,
                branches=4,
                merge_isomorphic=3,
            ),
        )
        iso = [key for key in built.graph.edges if key[2].startswith("iso::")]
        self.assertTrue(iso, "同构折叠被 --branches 压住了")

    def test_suppressed_members_are_recorded(self) -> None:
        """被预算挡住的上游要留痕，否则折叠判据没有依据。"""
        rule_set, result = self._chain()
        built = build_path_graph(
            rule_set,
            result,
            "item:minecraft:lectern",
            PathOptions(
                depth=4,
                expand_tags=True,
                expand_groups=True,
                branches=4,
                merge_isomorphic=3,
            ),
        )
        dropped = {
            node
            for node in built.graph.suppressed
            if node.startswith("item:minecraft:") and "_slab" in node
        }
        self.assertTrue(dropped, "被 --branches 挡住的台阶成员没有登记")

    def test_a_lone_member_never_folds(self) -> None:
        """从单个台阶出发时，上级 tag 只有 1 个成员在图里，不许折。"""
        rule_set, result = self._chain()
        built = build_path_graph(
            rule_set,
            result,
            "item:minecraft:oak_slab",
            PathOptions(
                depth=4,
                expand_tags=True,
                expand_groups=True,
                branches=0,
                merge_isomorphic=3,
            ),
        )
        iso = [key for key in built.graph.edges if key[2].startswith("iso::")]
        self.assertFalse(iso, f"单成员触发了折叠：{iso}")


class TargetHighlightTest(unittest.TestCase):
    """目标物品必须一眼可辨：它是本图的主角，其余都是它的来源。

    三个通道一起标（换色 + 双层边框 + 加粗）：只换色的话，色觉差异与
    黑白打印两种情况都区分不出来。
    """

    def _built(self):
        rule = _rule("r", "item:minecraft:x", ("item:minecraft:y",))
        rule_set, result = _world(
            "item:minecraft:x", "item:minecraft:y", rules=[rule]
        )
        return build_path_graph(
            rule_set, result, "item:minecraft:x", PathOptions(depth=2)
        )

    def test_graph_records_its_target(self) -> None:
        """目标是图的一部分，不是渲染参数。

        存成参数会让 `build_dot` 与 `render_html` 各自持有一份，可能不一致
        （标题写 A、图上高亮 B）。
        """
        self.assertEqual(self._built().graph.target, "item:minecraft:x")

    def test_target_line_carries_the_highlight(self) -> None:
        built = self._built()
        dot = build_dot(built.graph, PathOptions(depth=2))
        line = next(l for l in dot.splitlines() if "item:minecraft:x" in l)
        self.assertIn(f'fillcolor="{TARGET_FILL}"', line)
        self.assertIn(f'color="{TARGET_BORDER}"', line)
        self.assertIn("peripheries=2", line)
        self.assertIn("penwidth=2.4", line)

    def test_only_the_target_is_highlighted(self) -> None:
        built = self._built()
        dot = build_dot(built.graph, PathOptions(depth=2))
        highlighted = [l for l in dot.splitlines() if "peripheries=2" in l]
        self.assertEqual(len(highlighted), 1, "高亮了不止一个节点")

    def test_no_duplicate_attributes(self) -> None:
        """`.dot` 给人读，同一属性出现两次会让人怀疑哪个生效。"""
        built = self._built()
        dot = build_dot(built.graph, PathOptions(depth=2))
        line = next(l for l in dot.splitlines() if '"item:minecraft:x"' in l)
        # 按键解析，不能数 `color=`：那会同时命中 `fontcolor=`。
        inside = line[line.index("[") + 1 : line.rindex("]")]
        keys = [part.split("=", 1)[0].strip() for part in inside.split(", ")]
        self.assertEqual(len(keys), len(set(keys)), f"属性重复：{keys}")

    def test_target_wins_over_root_styling(self) -> None:
        """目标同时是分析起点时，「主角」比「它属于哪类节点」更该被看见。"""
        rule_set, result = _world("item:minecraft:x")
        built = build_path_graph(
            rule_set, result, "item:minecraft:x", PathOptions(depth=2)
        )
        dot = build_dot(built.graph, PathOptions(depth=2))
        line = next(l for l in dot.splitlines() if "item:minecraft:x" in l)
        self.assertIn("peripheries=2", line)


class FurnaceFamilyTest(unittest.TestCase):
    """三种炉子合成一类显示。

    源码里它们接受不同的 `RecipeType`（熔炉 SMELTING、高炉 BLASTING、
    烟熏炉 SMOKING），不是超集关系。但数据包里同一产物常同时有 smelting 与
    blasting 两个配方文件（原料产物完全一样，只是耗时耗材不同），图上画成
    两条并列来源会让人以为是两条不同途径。
    """

    def test_three_serializers_share_one_category(self) -> None:
        crafts = {
            serialize: craft_of(_rule(f"r{n}", "item:minecraft:x", (), serializer=serialize))
            for n, serialize in enumerate(
                ("minecraft:smelting", "minecraft:blasting", "minecraft:smoking")
            )
        }
        self.assertEqual(
            set(crafts.values()), {"烧炼"}, f"三种烧炼工艺没有归一：{crafts}"
        )

    def test_campfire_keeps_its_own_category(self) -> None:
        """营火不是炉子，也不接受上面三种配方类型，不能并进去。"""
        campfire = craft_of(
            _rule("r", "item:minecraft:x", (), serializer="minecraft:campfire_cooking")
        )
        self.assertNotEqual(campfire, "烧炼")

    def test_three_stations_share_one_display_name(self) -> None:
        names = {
            condition_label(f"station:minecraft:{ident}")
            for ident in ("furnace", "blast_furnace", "smoker")
        }
        self.assertEqual(names, {"熔炉"}, f"三个设备名没有归一：{names}")

    def test_smelting_and_blasting_collapse_into_one_group(self) -> None:
        """同一产物的熔炼与高炉配方要聚成一个 folder，不是两个。"""
        rules = [
            _rule(
                f"smelt{n}",
                "item:minecraft:nugget",
                (f"item:minecraft:thing{n}", "station:minecraft:furnace"),
                family="recipes",
                serializer="minecraft:smelting",
            )
            for n in range(3)
        ] + [
            _rule(
                f"blast{n}",
                "item:minecraft:nugget",
                (f"item:minecraft:thing{n}", "station:minecraft:blast_furnace"),
                family="recipes",
                serializer="minecraft:blasting",
            )
            for n in range(3)
        ]
        nodes = ["item:minecraft:nugget", "station:minecraft:furnace",
                 "station:minecraft:blast_furnace"]
        nodes += [f"item:minecraft:thing{n}" for n in range(3)]
        rule_set, result = _world(*nodes, rules=rules)
        built = build_path_graph(
            rule_set, result, "item:minecraft:nugget", PathOptions(depth=2)
        )

        folders = [k for k in built.graph.nodes if k.startswith("group::")]
        self.assertEqual(len(folders), 1, f"烧炼被拆成了 {len(folders)} 组")
        self.assertIn("烧炼", built.graph.nodes[folders[0]]["label"])
        self.assertIn("6 条", built.graph.nodes[folders[0]]["label"])


if __name__ == "__main__":
    unittest.main()
