"""IR 编译的单元测试：各族规则形状 + 知识表驱动的部分。

这些测试**不需要输入包**：它们直接喂合成事实。少数需要真实事实的断言
（交易族、约定覆盖）由 `test_ir_integration.py` 承担。

为什么值得单独测：IR 是「事实 → 规则」的唯一入口，规则形状错了，
阶段三的求解器不会报错，只会安静地给出错误的可达率。
"""

from __future__ import annotations

import unittest

from oa.facts import Fact, Prov
from oa.ir.bridges import (
    convention_transform_rules,
    entity_behaviour_rules,
    entity_source_rules,
    tool_rules,
)
from oa.ir.families.bindings import compile_bindings
from oa.ir.families.trades import compile_trades
from oa.ir.families.transforms import compile_transforms
from oa.ir.families.worldgen import compile_worldgen
from oa.ir.tags import TagMembers
from oa.solve.attribute import NO_RULE, UNOBTAINABLE, attribute
from oa.solve.fixpoint import solve


def _fact(kind: str, payload: dict) -> Fact:
    return Fact(kind=kind, payload=payload, prov=Prov(input="test", file="t.json"))


class TradeTest(unittest.TestCase):
    def test_wants_may_be_a_single_object(self) -> None:
        """`wants` 写成 `{count, id}` 时也必须取到物品。

        直接迭代 dict 会拿到 `"count"`、`"id"` 两个键，于是整族交易被判成
        「付款物不是物品」，一条规则也编不出来——这条断言钉住过那个 bug。
        """
        facts = [
            _fact(
                "trade",
                {
                    "profession": "armorer",
                    "layer": "offer",
                    "gives": {"count": 1, "id": "minecraft:iron_boots"},
                    "wants": {"count": 4, "id": "minecraft:emerald"},
                },
            )
        ]
        result = compile_trades(facts, {"minecraft:iron_boots", "minecraft:emerald"})
        self.assertEqual(len(result.rules), 1)
        rule = result.rules[0]
        self.assertEqual(rule.head, "item:minecraft:iron_boots")
        self.assertEqual(rule.body, ("assume:villager_trade", "item:minecraft:emerald"))
        self.assertEqual(rule.kind, "yield")

    def test_wants_may_be_a_list(self) -> None:
        facts = [
            _fact(
                "trade",
                {
                    "gives": {"count": 1, "id": "minecraft:bread"},
                    "wants": [{"count": 3, "id": "minecraft:emerald"}],
                    "additional_wants": [{"count": 1, "id": "minecraft:wheat"}],
                },
            )
        ]
        result = compile_trades(facts, {"minecraft:bread", "minecraft:emerald", "minecraft:wheat"})
        self.assertEqual(
            result.rules[0].body,
            (
                "assume:villager_trade",
                "item:minecraft:emerald",
                "item:minecraft:wheat",
            ),
        )

    def test_trade_set_is_not_an_offer(self) -> None:
        """`layer=set` 是「一级交易集合」的定义，没有货物，单独计数而不算解析失败。"""
        facts = [
            _fact(
                "trade",
                {
                    "layer": "set",
                    "profession": "armorer",
                    "trades_ref": "#minecraft:armorer/level_1",
                },
            )
        ]
        result = compile_trades(facts, set())
        self.assertEqual(result.rules, [])
        self.assertEqual(result.sets, 1)
        self.assertEqual(dict(result.unresolved), {})

    def test_wandering_trader_has_its_own_assumption(self) -> None:
        """流浪商人不依赖村庄、不补货，前提与职业村民不同，不能共用假设节点。

        共用会让 `knowledge/assumptions.toml` 的 `basis` 对其中一边失真，也让
        「关掉村庄前提还能拿到什么」无法单独观察（ADR 0017）。
        """
        facts = [
            _fact(
                "trade",
                {
                    "profession": "wandering_trader",
                    "layer": "offer",
                    "gives": {"count": 8, "id": "minecraft:oak_log"},
                    "wants": {"id": "minecraft:emerald"},
                },
            ),
            _fact(
                "trade",
                {
                    "profession": "armorer",
                    "layer": "offer",
                    "gives": {"count": 1, "id": "minecraft:iron_boots"},
                    "wants": {"id": "minecraft:emerald"},
                },
            ),
        ]
        result = compile_trades(
            facts,
            {"minecraft:oak_log", "minecraft:iron_boots", "minecraft:emerald"},
        )
        bodies = {rule.head: rule.body for rule in result.rules}
        self.assertEqual(
            bodies["item:minecraft:oak_log"],
            ("assume:wandering_trader", "item:minecraft:emerald"),
        )
        self.assertEqual(
            bodies["item:minecraft:iron_boots"],
            ("assume:villager_trade", "item:minecraft:emerald"),
        )

    def test_unknown_gives_is_recorded(self) -> None:
        facts = [
            _fact(
                "trade",
                {"gives": {"id": "minecraft:not_an_item"}, "wants": {"id": "minecraft:emerald"}},
            )
        ]
        result = compile_trades(facts, {"minecraft:emerald"})
        self.assertEqual(result.rules, [])
        self.assertIn("gives:minecraft:not_an_item", result.unresolved)


class ConventionTest(unittest.TestCase):
    def test_suffix_pairing(self) -> None:
        conventions = {
            "water_solidify": {
                "match_suffix": "_powder",
                "head": "{stem}",
                "body": "{stem}_powder",
                "requires": ["assume:water_source"],
                "basis": "test",
            }
        }
        blocks = {"minecraft:red_concrete", "minecraft:red_concrete_powder"}
        rules, stats = convention_transform_rules(blocks, conventions)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].head, "block:minecraft:red_concrete")
        self.assertEqual(
            rules[0].body,
            ("block:minecraft:red_concrete_powder", "assume:water_source"),
        )
        self.assertEqual(stats["water_solidify:paired"], 1)
        self.assertEqual(stats.get("water_solidify:miss", 0), 0)

    def test_prefix_pairing_and_stem_filter(self) -> None:
        """`match_prefix` 不带词干过滤时会把 `dead_bush` 配到 `bush` 上。

        26.3 里 `bush` 是方块，所以不过滤就会凭空造出「灌木长成枯灌木」。
        """
        spec = {
            "match_prefix": "dead_",
            "head": "dead_{stem}",
            "body": "{stem}",
        }
        without = convention_transform_rules(
            {"minecraft:dead_bush", "minecraft:bush", "minecraft:dead_brain_coral", "minecraft:brain_coral"},
            {"coral_death": spec},
        )
        self.assertEqual(len(without[0]), 2, "不过滤时两条都配对")

        filtered, stats = convention_transform_rules(
            {"minecraft:dead_bush", "minecraft:bush", "minecraft:dead_brain_coral", "minecraft:brain_coral"},
            {"coral_death": {**spec, "stem_contains": "coral"}},
        )
        self.assertEqual([r.head for r in filtered], ["block:minecraft:dead_brain_coral"])
        self.assertEqual(stats["coral_death:filtered"], 1)

    def test_unpaired_target_is_a_miss(self) -> None:
        conventions = {
            "c": {"match_suffix": "_powder", "head": "{stem}", "body": "{stem}_powder"}
        }
        rules, stats = convention_transform_rules({"minecraft:orphan_powder"}, conventions)
        self.assertEqual(rules, [])
        self.assertEqual(stats["c:miss"], 1)

    def test_empty_match_is_rejected(self) -> None:
        """两侧都空会命中整个注册表，那不是约定。"""
        conventions = {"c": {"head": "{stem}", "body": "{stem}"}}
        rules, stats = convention_transform_rules({"minecraft:stone"}, conventions)
        self.assertEqual(rules, [])
        self.assertEqual(stats["c:spec_invalid"], 1)


class ToolBridgeTest(unittest.TestCase):
    def test_singleton_tool_comes_from_its_item(self) -> None:
        """剪刀没有物品标签，但它仍是一座桥：`tool:shears ← item:shears`。

        照「只能由事实给」处理会让所有依赖剪刀的战利品规则全断。
        """
        rules, missing = tool_rules({"minecraft:shears": None}, {"minecraft:shears"})
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].head, "tool:minecraft:shears")
        self.assertEqual(rules[0].body, ("item:minecraft:shears",))
        self.assertEqual(missing, {})

    def test_singleton_without_matching_item_is_missing(self) -> None:
        rules, missing = tool_rules({"minecraft:shears": None}, set())
        self.assertEqual(rules, [])
        self.assertEqual(missing, {"minecraft:shears": -1})

    def test_tag_class_uses_the_tag(self) -> None:
        rules, _ = tool_rules({"minecraft:axe": "minecraft:axes"}, {"minecraft:iron_axe"})
        self.assertEqual(rules[0].body, ("tag:item/minecraft:axes",))


class BindingsTest(unittest.TestCase):
    def _template(
        self, blocks: list[str], file: str = "t.snbt", entities: list[dict] | None = None
    ) -> Fact:
        payload: dict = {"template": file, "blocks": blocks}
        if entities is not None:
            payload["entities"] = entities
        return Fact(
            kind="template",
            payload=payload,
            prov=Prov(input="src", file=file),
        )

    def _structure(self, ident: str, spawns: list[dict]) -> Fact:
        return Fact(
            kind="worldgen",
            payload={
                "worldgen_kind": "structure",
                "id": ident,
                "references": [],
                "spawns": spawns,
            },
            prov=Prov(input="src", file=f"{ident}.json"),
        )

    def test_state_suffix_is_stripped(self) -> None:
        """模板的 `blocks` 带方块状态（`grass_block{snowy:false}`），注册表里是裸名。"""
        facts = [self._template(["minecraft:grass_block{snowy:false}", "minecraft:stone"])]
        result = compile_bindings(
            facts, [], {"minecraft:grass_block", "minecraft:stone"}, set(), set(), set()
        )
        heads = {r.head for r in result.rules}
        self.assertEqual(
            heads, {"block:minecraft:grass_block", "block:minecraft:stone"}
        )

    def test_one_rule_per_block_across_templates(self) -> None:
        """同一方块出现在几十个模板里，只发一条规则。"""
        facts = [
            self._template(["minecraft:stone"], "a.snbt"),
            self._template(["minecraft:stone"], "b.snbt"),
        ]
        result = compile_bindings(facts, [], {"minecraft:stone"}, set(), set(), set())
        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.template_blocks, 1)

    def test_existing_head_still_gets_a_rule(self) -> None:
        """已有其它来源的规则时**仍要发**：同 head 多规则就是 OR。

        早先跳过，结果「有别的路径但都走不通」的方块失去了模板这条腿——
        铜傀儡像就卡在这儿：它的 head 被变换规则占了，于是模板证据被丢掉。
        """
        facts = [self._template(["minecraft:oxidized_copper_golem_statue"])]
        result = compile_bindings(
            facts,
            [],
            {"minecraft:oxidized_copper_golem_statue"},
            set(),
            set(),
            {"block:minecraft:oxidized_copper_golem_statue"},
        )
        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.already_seeded, 1)

    def test_unknown_template_block_is_recorded(self) -> None:
        facts = [self._template(["minecraft:not_a_block"])]
        result = compile_bindings(facts, [], {"minecraft:stone"}, set(), set(), set())
        self.assertEqual(result.rules, [])
        self.assertEqual(dict(result.unknown_block_ids), {"minecraft:not_a_block": 1})

    def test_structure_spawn_chain(self) -> None:
        facts = [
            self._structure(
                "src/main/resources/data/minecraft/worldgen/structure/monument",
                [{"entity": "minecraft:guardian", "category": "monster"}],
            )
        ]
        result = compile_bindings(
            [], facts, set(), {"minecraft:guardian"}, set(), set()
        )
        heads = {r.head: r for r in result.rules}
        self.assertIn("structure:minecraft:monument", heads)
        self.assertEqual(heads["entity:minecraft:guardian"].body, ("structure:minecraft:monument",))
        self.assertEqual(heads["entity:minecraft:guardian"].kind, "spawns")

    def test_reports_style_structure_id_falls_back(self) -> None:
        """运行期导出的 id 是 `configured_structure_feature/<名>`，不含命名空间。"""
        facts = [
            self._structure(
                "configured_structure_feature/fortress",
                [{"entity": "minecraft:blaze", "category": "monster"}],
            )
        ]
        result = compile_bindings([], facts, set(), {"minecraft:blaze"}, set(), set())
        self.assertIn(
            "structure:minecraft:fortress", {r.head for r in result.rules}
        )

    def test_unknown_spawn_entity_is_recorded(self) -> None:
        facts = [
            self._structure(
                "src/main/resources/data/minecraft/worldgen/structure/x",
                [{"entity": "minecraft:no_such_mob", "category": "monster"}],
            )
        ]
        result = compile_bindings([], facts, set(), set(), set(), set())
        self.assertEqual(dict(result.unknown_entities), {"minecraft:no_such_mob": 1})

    def test_template_entity_becomes_world_seeded(self) -> None:
        """模板 NBT 里的实体 → `entity:X ←seeds← world`。

        村民不由任何生物群系的刷怪表生成，模板里的 NBT 是它唯一的数据包踪迹。
        不读它，`entity:villager` 为零规则、状态 FALSE，所有以村民为前提的
        机制一起断链（交易在代码侧形态因此整批恒假）。
        """
        facts = [
            self._template(
                ["minecraft:bookshelf"],
                "village/plains/houses/plains_library_1.snbt",
                entities=[{"id": "minecraft:villager", "has_equipment": True}],
            )
        ]
        result = compile_bindings(facts, [], {"minecraft:bookshelf"}, {"minecraft:villager"}, set(), set())
        heads = {r.head: r for r in result.rules}
        self.assertIn("entity:minecraft:villager", heads)
        rule = heads["entity:minecraft:villager"]
        self.assertEqual(rule.body, ("world:minecraft:overworld",))
        self.assertEqual(rule.kind, "seeds")
        self.assertEqual(rule.family, "bindings/template_entity")
        self.assertEqual(result.template_entities, 1)

    def test_one_rule_per_entity_across_templates(self) -> None:
        """同一实体出现在十几个模板里，只发一条规则。"""
        facts = [
            self._template([], "a.snbt", entities=[{"id": "minecraft:villager"}]),
            self._template([], "b.snbt", entities=[{"id": "minecraft:villager"}]),
        ]
        result = compile_bindings(facts, [], set(), {"minecraft:villager"}, set(), set())
        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.template_entities, 1)

    def test_template_entity_not_in_registry_is_recorded(self) -> None:
        """模板 `entities` 里也会有非实体 id（26.3 的 `minecraft:cushion` 是方块实体）。

        静默跳过会让「模板里这个实体没接上」永远发现不了；必须进 `unknown_entities`。
        """
        facts = [
            self._template([], "t.snbt", entities=[{"id": "minecraft:cushion"}])
        ]
        result = compile_bindings(facts, [], set(), {"minecraft:villager"}, set(), set())
        self.assertEqual(result.rules, [])
        self.assertEqual(dict(result.unknown_entities), {"minecraft:cushion": 1})


class EntityBehaviourTest(unittest.TestCase):
    """`entity_behaviour`：行为产出。

    这张表存在的理由就是「产出的代码形态各不相同」——所以测试也按形态分组，
    每种形态各一条，钉住 actor 可以是任何排序的节点。
    """

    def _behaviour(self, spec: dict) -> dict:
        return {"case": spec}

    def test_entity_actor_makes_a_yield_rule(self) -> None:
        rules, problems = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["item:minecraft:dragon_breath"],
                    "actor": "entity:minecraft:ender_dragon",
                    "inputs": ["item:minecraft:glass_bottle"],
                    "basis": "",
                    "evidence": "",
                }
            )
        )
        self.assertEqual(problems, {})
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule.head, "item:minecraft:dragon_breath")
        self.assertEqual(rule.kind, "yield")
        self.assertEqual(
            rule.body,
            ("entity:minecraft:ender_dragon", "item:minecraft:glass_bottle"),
        )

    def test_block_can_be_the_actor(self) -> None:
        """青蛙卵孵化：主体是方块，不是实体。"""
        rules, _ = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["entity:minecraft:tadpole"],
                    "actor": "block:minecraft:frogspawn",
                    "inputs": [],
                }
            )
        )
        self.assertEqual(rules[0].head, "entity:minecraft:tadpole")
        self.assertEqual(rules[0].body, ("block:minecraft:frogspawn",))

    def test_assumption_can_be_the_actor(self) -> None:
        """玩家书写：主体是玩家，用假设节点。"""
        rules, _ = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["item:minecraft:written_book"],
                    "actor": "assume:player",
                    "inputs": ["item:minecraft:writable_book"],
                }
            )
        )
        self.assertEqual(
            rules[0].body, ("assume:player", "item:minecraft:writable_book")
        )

    def test_world_can_be_the_actor(self) -> None:
        """树生成时挂蜂巢：主体是世界。"""
        rules, _ = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["block:minecraft:bee_nest"],
                    "actor": "world:minecraft:overworld",
                    "inputs": [],
                }
            )
        )
        self.assertEqual(rules[0].body, ("world:minecraft:overworld",))

    def test_multiple_produces_make_multiple_rules(self) -> None:
        rules, _ = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["item:minecraft:a", "block:minecraft:b"],
                    "actor": "assume:player",
                    "inputs": [],
                }
            )
        )
        self.assertEqual({r.head for r in rules}, {"item:minecraft:a", "block:minecraft:b"})
        # id 必须唯一：一次声明多个产出时靠序号区分
        self.assertEqual(len({r.id for r in rules}), 2)

    def test_bad_node_is_recorded_not_raised(self) -> None:
        rules, problems = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["item:minecraft:a"],
                    "actor": "not_a_node",
                    "inputs": [],
                }
            )
        )
        self.assertEqual(rules, [])
        self.assertEqual(problems, {"case:bad_node": 1})

    def test_missing_produces_is_recorded(self) -> None:
        rules, problems = entity_behaviour_rules({"case": {"actor": "assume:player"}})
        self.assertEqual(rules, [])
        self.assertEqual(problems, {"case:no_produces": 1})

    def test_bad_produce_node_skips_rest_of_that_entry(self) -> None:
        """产出里混入非法节点时整条不产，而不是产一半。"""
        rules, problems = entity_behaviour_rules(
            self._behaviour(
                {
                    "produces": ["item:minecraft:a", "bogus"],
                    "actor": "assume:player",
                    "inputs": [],
                }
            )
        )
        self.assertEqual([r.head for r in rules], ["item:minecraft:a"])
        self.assertEqual(problems, {"case:bad_produces": 1})


class EntitySourceTest(unittest.TestCase):
    """`entity_sources`：不来自世界生成的实体。"""

    def test_summon_kind(self) -> None:
        rules, problems = entity_source_rules(
            {
                "minecraft:wither": {
                    "kind": "summon",
                    "requires": ["tag:block/minecraft:wither_summon_base_blocks"],
                    "pattern": "T 形底座",
                    "basis": "",
                }
            }
        )
        self.assertEqual(problems, {})
        self.assertEqual(rules[0].head, "entity:minecraft:wither")
        self.assertEqual(rules[0].kind, "spawns")
        self.assertEqual(rules[0].meta["source_kind"], "summon")

    def test_dimension_kind(self) -> None:
        """末影龙不经 biome spawner，用维度假设当依据。"""
        rules, _ = entity_source_rules(
            {
                "minecraft:ender_dragon": {
                    "kind": "dimension",
                    "requires": ["assume:end"],
                    "basis": "",
                }
            }
        )
        self.assertEqual(rules[0].body, ("assume:end",))
        self.assertEqual(rules[0].meta["source_kind"], "dimension")

    def test_unknown_kind_is_recorded(self) -> None:
        """未知 kind 不能静默当成 summon——它会悄悄造出一条错的规则。"""
        rules, problems = entity_source_rules(
            {"x": {"kind": "spawned_by_magic", "requires": ["assume:player"]}}
        )
        self.assertEqual(rules, [])
        self.assertIn("x:unknown_kind:spawned_by_magic", problems)

    def test_node_key_may_omit_prefix(self) -> None:
        rules, _ = entity_source_rules(
            {"minecraft:wither": {"kind": "dimension", "requires": ["assume:end"]}}
        )
        self.assertEqual(rules[0].head, "entity:minecraft:wither")


class ExceptionAttributionTest(unittest.TestCase):
    """例外表把 `no_rule` 拆成「确定拿不到」与「机制尚未提取」。"""

    def _result(self):
        from oa.ir.nodes import RuleSet

        return RuleSet(), solve(RuleSet(), [])

    def test_exception_hit_is_unobtainable(self) -> None:
        rules, result = self._result()
        attribution = attribute(
            "item:minecraft:bedrock",
            rules,
            result,
            exceptions={"minecraft:bedrock": {"category": "不可破坏", "basis": "挖不下来"}},
        )
        self.assertEqual(attribution.reason, UNOBTAINABLE)
        self.assertIn("不可破坏", attribution.note)

    def test_exception_absent_stays_no_rule(self) -> None:
        rules, result = self._result()
        attribution = attribute("item:minecraft:filled_map", rules, result, exceptions={})
        self.assertEqual(attribution.reason, NO_RULE)

    def test_exception_accepts_full_node_key(self) -> None:
        rules, result = self._result()
        attribution = attribute(
            "item:minecraft:bedrock",
            rules,
            result,
            exceptions={"item:minecraft:bedrock": {"category": "不可破坏", "basis": ""}},
        )
        self.assertEqual(attribution.reason, UNOBTAINABLE)


class TransformInverseTest(unittest.TestCase):
    def test_inverse_rule_needs_the_other_prerequisite(self) -> None:
        """刮削的反方向是自然氧化：同一对前提之外的差别只有「需要什么」。"""
        facts = [
            _fact(
                "block_transform",
                {
                    "to": "block:minecraft:weathered_copper",
                    "from": ["block:minecraft:oxidized_copper"],
                    "sound": "minecraft:item.axe.scrape",
                    "transformer": "minecraft:axe",
                    "transformer_kind": "registry",
                },
            )
        ]
        result = compile_transforms(
            facts,
            {"minecraft:axe": "minecraft:axes"},
            {"minecraft:item.axe.scrape": {"requires": ["assume:time"], "basis": "test"}},
        )
        heads = {r.head: r for r in result.rules}
        self.assertIn("block:minecraft:weathered_copper", heads)
        self.assertIn("block:minecraft:oxidized_copper", heads)
        inverse = heads["block:minecraft:oxidized_copper"]
        self.assertEqual(
            inverse.body, ("block:minecraft:weathered_copper", "assume:time")
        )
        self.assertTrue(inverse.meta.get("inverse"))

    def test_sound_without_entry_has_no_inverse(self) -> None:
        facts = [
            _fact(
                "block_transform",
                {
                    "to": "block:minecraft:stripped_oak_log",
                    "from": ["block:minecraft:oak_log"],
                    "sound": "minecraft:item.axe.strip",
                    "transformer": "minecraft:axe",
                    "transformer_kind": "registry",
                },
            )
        ]
        result = compile_transforms(
            facts,
            {"minecraft:axe": "minecraft:axes"},
            {"minecraft:item.axe.scrape": {"requires": ["assume:time"]}},
        )
        self.assertEqual(len(result.rules), 1, "剥皮不可逆，只产正方向")


class WorldgenTagPlacementTest(unittest.TestCase):
    def _tag_fact(self, tag: str, values: list[str], nested: list[str] | None = None) -> Fact:
        return _fact(
            "tag",
            {
                "registry": "minecraft:block",
                "tag": tag,
                "values": values,
                "nested": nested or [],
            },
        )

    def test_placed_tag_expands_to_members(self) -> None:
        """`blocks: #minecraft:corals` 是「从标签里选一个放置」。

        存在性语义下每个成员的概率都非零，于是每个成员都能在某处生成。
        """
        worldgen = [
            _fact(
                "worldgen",
                {
                    "worldgen_kind": "feature",
                    "id": "f",
                    "type": "overlay",
                    "references": [{"slot": "tag", "id": "minecraft:corals"}],
                },
            )
        ]
        tags = [self._tag_fact("minecraft:corals", ["minecraft:brain_coral", "minecraft:tube_coral"])]
        result = compile_worldgen(worldgen, set(), set(), TagMembers(tags))
        heads = {r.head for r in result.rules}
        self.assertIn("tag:block/minecraft:corals", heads)
        self.assertIn("block:minecraft:brain_coral", heads)
        self.assertIn("block:minecraft:tube_coral", heads)
        self.assertNotIn("tag", result.unresolved_refs)

    def test_nested_tag_members_are_flattened(self) -> None:
        worldgen = [
            _fact(
                "worldgen",
                {
                    "worldgen_kind": "feature",
                    "id": "f",
                    "references": [{"slot": "tag", "id": "minecraft:outer"}],
                },
            )
        ]
        tags = [
            self._tag_fact("minecraft:outer", [], ["minecraft:inner"]),
            self._tag_fact("minecraft:inner", ["minecraft:sea_pickle"]),
        ]
        result = compile_worldgen(worldgen, set(), set(), TagMembers(tags))
        self.assertIn("block:minecraft:sea_pickle", {r.head for r in result.rules})

    def test_unknown_tag_is_recorded(self) -> None:
        worldgen = [
            _fact(
                "worldgen",
                {
                    "worldgen_kind": "feature",
                    "id": "f",
                    "references": [{"slot": "tag", "id": "minecraft:no_such_tag"}],
                },
            )
        ]
        result = compile_worldgen(worldgen, set(), set(), TagMembers([]))
        self.assertEqual(result.rules, [])
        self.assertEqual(result.unresolved_refs["tag"], 1)

    def test_registry_anchoring_overrides_slot(self) -> None:
        """`slot=entity` 是兜底；命中方块注册表就按方块排。"""
        worldgen = [
            _fact(
                "worldgen",
                {
                    "worldgen_kind": "noise_settings",
                    "id": "n",
                    "references": [{"slot": "entity", "id": "minecraft:stone"}],
                },
            )
        ]
        result = compile_worldgen(worldgen, {"minecraft:stone"}, set())
        self.assertEqual([r.head for r in result.rules], ["block:minecraft:stone"])
        self.assertEqual(result.anchored_by_registry["entity→block"], 1)


if __name__ == "__main__":
    unittest.main()
