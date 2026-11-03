"""事实 → 规则。

只有一种形状，`head ← body`，OR 由多条同 head 表达。

## 装配顺序

1. 读知识表（假设、设备映射、条件分类）
2. 编译各族事实 → 规则（recipes / loot / code / worldgen）
3. 编译桥接 → 规则（tag 展开、station、表产出者）
4. 播种（`assume:*` 与 `world:*` 初始为真）

顺序有依赖：桥接要看到全部 item/block 注册项，才能判断约定是否成立。

## 未登记即硬失败

未登记的条件类型、未登记的 serializer 都要报，不静默当默认值。
本模块汇总这些异常到 `CompileReport`，由 CLI 决定是否中止——
`--allow-unknown` 时照常产出报告但有台账，默认则硬失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..facts import Fact, FactStore
from .bridges import (
    BridgeResult,
    convention_transform_rules,
    derive_capabilities,
    enchant_rules,
    entity_behaviour_rules,
    entity_source_rules,
    harvest_rules,
    place_rules,
    station_rules,
    table_provider_rules,
    tag_rules,
    tool_rules,
)
from .families.bindings import compile_bindings
from .families.code import compile_code
from .families.loot import compile_loot
from .families.recipes import compile_recipes
from .families.transforms import compile_transforms
from .families.trades import compile_trades
from .families.worldgen import compile_worldgen
from .knowledge import (
    MECHANISM,
    VOCABULARY,
    KnowledgeError,
    load_assumptions,
    load_condition_kinds,
    load_map,
)
from .nodes import Rule, RuleSet, node
from .tags import TagMembers

IR_SCHEMA = 1


@dataclass
class CompileReport:
    """编译期的可审查结果：计数、异常、未映射项。"""

    rule_counts: dict[str, int] = field(default_factory=dict)
    seeds: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # 必须让调用方看见的问题
    unknown_conditions: dict[str, int] = field(default_factory=dict)
    unknown_serializers: dict[str, int] = field(default_factory=dict)
    unresolved_conditions: dict[str, int] = field(default_factory=dict)
    combinator_conditions: dict[str, int] = field(default_factory=dict)
    # `any_of` 里全是可映射硬条件时，展开成同 head 多条规则（OR）
    combinator_expanded: dict[str, int] = field(default_factory=dict)
    # OR 组合数超过上限而放弃展开的表
    combinator_overflow: dict[str, int] = field(default_factory=dict)
    # 工具能力：可推的方块数、工具数、组件读不懂的物品、查不到的标签引用
    harvest_blocks: int = 0
    harvest_tools: int = 0
    harvest_unreadable: list[str] = field(default_factory=list)
    harvest_unresolved_refs: dict[str, int] = field(default_factory=dict)
    # 工具要求整族不可用时的原因（旧版本没有组件系统）
    harvest_unavailable: str = ""
    dynamic_tables: list[str] = field(default_factory=list)
    missing_stations: list[str] = field(default_factory=list)
    # 战利品表的 tag 条目里标签名查不到成员，或成员不是物品
    unresolved_tag_entries: dict[str, int] = field(default_factory=dict)
    unknown_tag_members: dict[str, int] = field(default_factory=dict)
    table_convention: dict[str, int] = field(default_factory=dict)
    # 引用排序由注册表锚定纠正的次数（如 slot=entity 实际是方块）
    anchored_by_registry: dict[str, int] = field(default_factory=dict)
    # 既不在 block 也不在 entity 注册表的引用（生成器、谓词等）
    unresolved_slots: dict[str, int] = field(default_factory=dict)
    # 自指配方（复制类）不是入口，不产规则；无原料配方留给归因
    self_referential_recipes: int = 0
    no_ingredient_recipes: int = 0
    # 变换器没有工具类映射（代码表里的私有映射）
    unmapped_transformers: dict[str, int] = field(default_factory=dict)
    unknown_transformer_kinds: list[str] = field(default_factory=list)
    # 工具类没有对应物品标签（只能由事实给）
    tools_without_tag: dict[str, int] = field(default_factory=dict)
    # 有方块但没有对应物品（墙上的火把这类），物品侧另有路径
    blocks_without_item: int = 0
    # 交易事实里付款物或货物不是物品的条目（标签、按组件指定）
    unresolved_trades: dict[str, int] = field(default_factory=dict)
    trades_by_profession: dict[str, int] = field(default_factory=dict)
    trade_sets: int = 0
    # 后缀约定变换的覆盖率（命中 / 配对 / 配不上）
    convention_transforms: dict[str, int] = field(default_factory=dict)
    # 召唤/维度实体表与行为表里的问题（节点不合法、缺字段）
    entity_source_problems: dict[str, int] = field(default_factory=dict)
    entity_behaviour_problems: dict[str, int] = field(default_factory=dict)
    # 模板里出现、但在方块注册表查不到的 id
    unknown_template_blocks: dict[str, int] = field(default_factory=dict)
    # 模板方块总数 / 已被世界生成覆盖数 / 结构刷怪实体数
    template_blocks: int = 0
    template_blocks_already_seeded: int = 0
    spawned_entities: int = 0
    # 模板 NBT 里直接写着的实体种类（村民、猫、铁傔儡…）
    template_entities: int = 0
    # 结构刷怪里实体不在注册表的条目
    unknown_spawn_entities: dict[str, int] = field(default_factory=dict)
    # 模板方块实体里装着的物品：绑定数、未知物品 id、方块实体类型不是方块名
    template_items: int = 0
    unknown_template_item_ids: dict[str, int] = field(default_factory=dict)
    unknown_template_item_holders: dict[str, int] = field(default_factory=dict)

    def as_json(self) -> dict:
        return {
            "ir_schema": IR_SCHEMA,
            "rule_counts": self.rule_counts,
            "seed_count": len(self.seeds),
            "unknown_conditions": self.unknown_conditions,
            "unknown_serializers": self.unknown_serializers,
            "unresolved_conditions": self.unresolved_conditions,
            "combinator_conditions": self.combinator_conditions,
            "combinator_expanded": self.combinator_expanded,
            "combinator_overflow": self.combinator_overflow,
            "harvest_blocks": self.harvest_blocks,
            "harvest_tools": self.harvest_tools,
            "harvest_unreadable": self.harvest_unreadable,
            "harvest_unresolved_refs": self.harvest_unresolved_refs,
            "harvest_unavailable": self.harvest_unavailable,
            "dynamic_table_count": len(self.dynamic_tables),
            "missing_stations": self.missing_stations,
            "unresolved_tag_entries": self.unresolved_tag_entries,
            "unknown_tag_members": self.unknown_tag_members,
            "table_convention": self.table_convention,
            "anchored_by_registry": self.anchored_by_registry,
            "unresolved_slots": self.unresolved_slots,
            "self_referential_recipes": self.self_referential_recipes,
            "no_ingredient_recipes": self.no_ingredient_recipes,
            "unmapped_transformers": self.unmapped_transformers,
            "unknown_transformer_kinds": self.unknown_transformer_kinds,
            "tools_without_tag": self.tools_without_tag,
            "blocks_without_item": self.blocks_without_item,
            "unresolved_trades": self.unresolved_trades,
            "trades_by_profession": self.trades_by_profession,
            "trade_sets": self.trade_sets,
            "convention_transforms": self.convention_transforms,
            "entity_source_problems": self.entity_source_problems,
            "entity_behaviour_problems": self.entity_behaviour_problems,
            "unknown_template_blocks": self.unknown_template_blocks,
            "template_blocks": self.template_blocks,
            "template_blocks_already_seeded": self.template_blocks_already_seeded,
            "spawned_entities": self.spawned_entities,
            "template_entities": self.template_entities,
            "unknown_spawn_entities": self.unknown_spawn_entities,
            "template_items": self.template_items,
            "unknown_template_item_ids": self.unknown_template_item_ids,
            "unknown_template_item_holders": self.unknown_template_item_holders,
            "notes": self.notes,
        }


def _registry_entries(store: FactStore, registry: str) -> set[str]:
    for fact in store.of_kind("registry"):
        if fact.payload.get("registry") == registry:
            return set(fact.payload["entries"])
    return set()


def compile_ir(store: FactStore, root: Path) -> tuple[RuleSet, CompileReport]:
    """把事实库编译成规则集合。

    知识表在开头一次性读完，各阶段只拿数据不碰文件：一张表被两个阶段共用时
    （如 `tool_class` 同时供变换与工具桥接），重复读盘不仅多一次 IO，
    还会让「两处读的是不是同一份」变成需要逐次确认的事。
    """
    report = CompileReport()

    assume_seeds = load_assumptions(root)
    station_map = {
        k: (v if v is None else str(v))
        for k, v in load_map(root, VOCABULARY, "serializer_station").items()
    }
    condition_kinds = load_condition_kinds(root)
    tool_class = load_map(root, VOCABULARY, "tool_class")
    transform_inverse = load_map(root, MECHANISM, "transform_inverse")
    entity_source_map = load_map(root, MECHANISM, "entity_sources")
    entity_behaviour_map = load_map(root, MECHANISM, "entity_behaviour")
    transform_conventions = load_map(root, MECHANISM, "transform_conventions")
    table_provider_map = load_map(root, MECHANISM, "table_providers")

    rule_set = RuleSet()
    # 标签成员表：loot 与 worldgen 都要用它展开「随机抽一个」的条目，
    # 只算一次。两份实现漂移过（各自漏过不同写法），所以抽成共用对象。
    tag_members = TagMembers(store.of_kind("tag"))
    item_ids = _registry_entries(store, "minecraft:item")
    block_ids = _registry_entries(store, "minecraft:block")
    entity_ids = _registry_entries(store, "minecraft:entity_type")

    # 工具能力要在 loot 之前算：`blocks/<方块>` 表的每条掉落都以「采得动这个方块」
    # 为前提，而那个前提只能从物品的工具组件反推。
    component_facts = store.of_kind("components")
    harvest = derive_capabilities(component_facts, tag_members)
    report.harvest_blocks = harvest.blocks
    report.harvest_tools = harvest.tools
    report.harvest_unreadable = list(harvest.unreadable_tools)
    report.harvest_unresolved_refs = dict(harvest.unresolved_refs)
    if harvest.tools == 0:
        # 旧版（组件系统之前）没有 `minecraft:tool`，工具要求整族不可用。
        # 必须显式登记：否则「路径里没有工具」与「根本没有这条链」在产物上
        # 长得一模一样，读者会以为工具真的不需要。
        report.harvest_unavailable = (
            "输入无物品组件（minecraft:tool），工具要求无法推导"
            if not component_facts
            else "物品组件里没有 minecraft:tool，工具要求无法推导"
        )

    # ---- 各族 ----
    recipe_result = compile_recipes(store.of_kind("recipe"), station_map)
    rule_set.extend(recipe_result.rules)
    report.rule_counts["recipes"] = len(recipe_result.rules)
    report.unknown_serializers = dict(recipe_result.unknown_serializers)
    report.self_referential_recipes = len(recipe_result.self_referential)
    report.no_ingredient_recipes = len(recipe_result.no_ingredient)

    loot_result = compile_loot(
        store.of_kind("loot_table"),
        condition_kinds,
        tag_members,
        item_ids,
        harvest.capabilities,
    )
    rule_set.extend(loot_result.rules)
    report.rule_counts["loot"] = len(loot_result.rules)
    report.unknown_conditions = dict(loot_result.unknown_conditions)
    report.unresolved_conditions = dict(loot_result.unresolved)
    report.combinator_conditions = dict(loot_result.combinators)
    report.combinator_expanded = dict(loot_result.combinator_expanded)
    report.combinator_overflow = dict(loot_result.combinator_overflow)
    report.dynamic_tables = list(loot_result.dynamic_tables)
    report.unresolved_tag_entries = dict(loot_result.unresolved_tag_entries)
    report.unknown_tag_members = dict(loot_result.unknown_tag_members)

    code_rules = compile_code(store.of_kind("code_link"))
    rule_set.extend(code_rules)
    report.rule_counts["code"] = len(code_rules)

    trade_result = compile_trades(store.of_kind("trade"), item_ids)
    rule_set.extend(trade_result.rules)
    report.rule_counts["trades"] = len(trade_result.rules)
    report.unresolved_trades = dict(trade_result.unresolved)
    report.trades_by_profession = dict(trade_result.by_profession)
    report.trade_sets = trade_result.sets

    worldgen_result = compile_worldgen(
        store.of_kind("worldgen"), block_ids, entity_ids, tag_members
    )
    rule_set.extend(worldgen_result.rules)
    report.rule_counts["worldgen"] = len(worldgen_result.rules)
    report.anchored_by_registry = dict(worldgen_result.anchored_by_registry)
    report.unresolved_slots = dict(worldgen_result.unresolved_refs)

    transform_result = compile_transforms(
        store.of_kind("block_transform"),
        tool_class,
        transform_inverse,
    )
    rule_set.extend(transform_result.rules)
    report.rule_counts["transforms"] = len(transform_result.rules)
    report.unmapped_transformers = dict(transform_result.unmapped_transformer)
    report.unknown_transformer_kinds = list(transform_result.unknown_transformer_kind)

    # `bindings` 要在 `worldgen` 之后：结构节点可能已由世界生成播种，
    # 传进去避免同一节点发两遍规则
    bindings_result = compile_bindings(
        store.of_kind("template"),
        store.of_kind("worldgen"),
        block_ids,
        entity_ids,
        item_ids,
        set(rule_set.by_head),
        store.of_kind("spawner_config"),
    )
    rule_set.extend(bindings_result.rules)
    report.rule_counts["bindings"] = len(bindings_result.rules)
    report.unknown_template_blocks = dict(bindings_result.unknown_block_ids)
    report.template_blocks = bindings_result.template_blocks
    report.template_blocks_already_seeded = bindings_result.already_seeded
    report.spawned_entities = bindings_result.spawned_entities
    report.template_entities = bindings_result.template_entities
    report.unknown_spawn_entities = dict(bindings_result.unknown_entities)
    report.template_items = bindings_result.template_items
    report.unknown_template_item_ids = dict(bindings_result.unknown_item_ids)
    report.unknown_template_item_holders = dict(bindings_result.unknown_item_holders)

    # ---- 桥接 ----
    tag = tag_rules(store.of_kind("tag"))
    rule_set.extend(tag)
    report.rule_counts["bridge/tag"] = len(tag)

    tool, tools_without_tag = tool_rules(tool_class, item_ids)
    rule_set.extend(tool)
    report.rule_counts["bridge/tool"] = len(tool)
    report.tools_without_tag = tools_without_tag

    harvest_link = harvest_rules(harvest)
    rule_set.extend(harvest_link)
    report.rule_counts["bridge/harvest"] = len(harvest_link)

    used_stations = {s for s in station_map.values() if s}
    # 图案超出 2x2 的配方也会用到工作台，但那个是 recipes 内部拼的 body 节点，
    # 同样要有 station 规则，否则 3x3 配方全线断
    for rule in rule_set.rules:
        for target in rule.body:
            if target.startswith("station:"):
                used_stations.add(target.split(":", 1)[1])
    station, missing = station_rules(sorted(used_stations), item_ids)
    rule_set.extend(station)
    report.rule_counts["bridge/station"] = len(station)
    report.missing_stations = missing

    enchant = enchant_rules(rule_set)
    rule_set.extend(enchant)
    report.rule_counts["bridge/enchant"] = len(enchant)

    source_rules, source_problems = entity_source_rules(entity_source_map)
    rule_set.extend(source_rules)
    report.rule_counts["bridge/entity_source"] = len(source_rules)
    report.entity_source_problems = source_problems

    behaviour_rules, behaviour_problems = entity_behaviour_rules(entity_behaviour_map)
    rule_set.extend(behaviour_rules)
    report.rule_counts["bridge/entity_behaviour"] = len(behaviour_rules)
    report.entity_behaviour_problems = behaviour_problems

    place, blocks_without_item = place_rules(block_ids, item_ids)
    rule_set.extend(place)
    report.rule_counts["bridge/place"] = len(place)
    report.blocks_without_item = blocks_without_item

    convention, convention_stats = convention_transform_rules(
        block_ids, transform_conventions
    )
    rule_set.extend(convention)
    report.rule_counts["bridge/convention"] = len(convention)
    report.convention_transforms = convention_stats

    holds_from_code = [r for r in rule_set.rules if r.kind == "holds" and r.head.startswith("table:")]
    provider, convention = table_provider_rules(
        store.of_kind("loot_table"), holds_from_code, block_ids, entity_ids, table_provider_map
    )
    # `holds_from_code` 已进规则集，这里只加目录约定产出的那部分
    added = [r for r in provider if r.id.startswith("bridge:table:")]
    rule_set.extend(added)
    report.rule_counts["bridge/table"] = len(added)
    report.table_convention = convention

    # ---- 播种 ----
    #
    # `assume:*` 由假设清单给；`world:*` 由世界生成事实的存在性给
    # （存在性语义：定义了就是有）。`entity/block/structure` 不直接播种——
    # 它们必须由 seeds 规则从 world 推出，否则「世界里有什么」的链条就断了。
    world_nodes = {
        target
        for rule in rule_set.rules
        for target in rule.body
        if target.startswith("world:")
    }
    report.seeds = sorted(set(assume_seeds) | world_nodes)

    if report.unknown_conditions:
        report.notes.append(
            f"{len(report.unknown_conditions)} 种条件类型未登记在 condition_kinds.json"
        )
    if report.unresolved_conditions:
        report.notes.append(
            f"{sum(report.unresolved_conditions.values())} 个条件已知是硬前置但内容不可得"
            "（主要是 match_tool：事实里只有类型没有谓词内容）"
        )
    if report.harvest_unavailable:
        report.notes.append(f"工具要求不可用：{report.harvest_unavailable}")
    if report.combinator_overflow:
        report.notes.append(
            f"{len(report.combinator_overflow)} 个表的 OR 组合数超过上限，未展开"
        )
    if report.harvest_unreadable:
        report.notes.append(
            f"{len(report.harvest_unreadable)} 个带工具组件的物品推不出能力："
            f"{', '.join(report.harvest_unreadable[:5])}"
        )
    if report.missing_stations:
        report.notes.append(
            f"{len(report.missing_stations)} 个设备不在物品注册表里，station 节点不会成立"
        )
    if report.unknown_template_blocks:
        report.notes.append(
            f"{len(report.unknown_template_blocks)} 个模板方块不在方块注册表里，未接进获取链"
        )
    if report.unknown_spawn_entities:
        report.notes.append(
            f"{len(report.unknown_spawn_entities)} 个结构刷怪实体不在注册表里，未接进获取链"
        )
    if report.template_entities:
        report.notes.append(
            f"模板 NBT 里的实体 {report.template_entities} 种已接进获取链（村民、猫、铁傀儡…）"
        )
    if report.unresolved_tag_entries:
        report.notes.append(
            f"{len(report.unresolved_tag_entries)} 个战利品表标签条目查不到成员"
        )
    if report.unknown_tag_members:
        report.notes.append(
            f"{len(report.unknown_tag_members)} 个战利品表标签成员不在物品注册表里"
        )

    report.rule_counts["total"] = len(rule_set.rules)
    return rule_set, report
