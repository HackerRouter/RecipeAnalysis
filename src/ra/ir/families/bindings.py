"""绑定族：把「谁在哪」的两类关系接进获取链。

`bindings` 族。这两类关系都不产出物品，只提供**前提**：

| 绑定 | 产物 | 来源 |
|---|---|---|
| 结构模板里的方块 | `block:X ←seeds← world` | `template` 事实的 `blocks` |
| 结构的刷怪配置 | `entity:X ←spawns← structure:Y` | `worldgen` 事实的 `spawns` |

## 为什么模板方块要接到 world

`block` 节点的现有来源只有两条：世界生成 feature 的 `references`（地表方块）
与 `bridge:place`（`block ← item`）。后者是反向的——它要求先有物品。
于是**只出现在结构里的方块**两条都不沾：铜傀儡像、雕刻南瓜、损坏的铁砧。
它们的 `item ← table ← block` 链整段悬空，归因落在「自指成环」。

模板是这三类方块的唯一事实来源。模板只可能作为结构的一部分生成，而结构
已由 `worldgen` 事实确认可生成（§5.0 的存在性语义），所以「模板里有这个方块」
足以断定「世界里生成得出这个方块」。这一步跨了「属于哪个结构」这一层，
是桥接层的正当职责：要精确到结构得先能可靠地把模板归到结构，而目录名
与结构名并不一一对应（`abandoned_camp/` 对应 18 个 `abandoned_camp_*`）。

**不会把不可获取的方块混进来**：`block → item` 只经战利品表，
而战利品表正是「挖掉它掉什么」的事实来源。原版不给 `bedrock`、`barrier`、
`command_block` 发战利品表，所以即使这些方块在模板里（`bedrock` 确实在），
也不会产出物品规则。这条性质由事实保证，不需要在这里特判。

## 为什么结构的刷怪要单独接

`spawn_overrides` 是结构 JSON 里「会冒出什么实体」的唯一数据包来源。
没有它，`guardian`、`witch`、`pillager`、`blaze` 这些只在结构里刷的实体
进不了 IR，它们的掉落链（`elder_guardian → tide_armor_trim_smithing_template`、
`evoker → totem_of_undying`）全线断。

节点形状沿用 `slot=structure` 引用的既有约定：`structure:<命名空间>:<名>`。
结构自身要有 `← world` 的规则才能为真；已有就复用，没有才补一条。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ...facts import Fact
from ..nodes import Rule, node

FAMILY = "bindings"
DEFAULT_WORLD = "world:minecraft:overworld"
# 「结构里装进去的东西可取得」——结构生成代码里的实体与刷怪笼共用这一条
SPAWNED_CONTENT = "assume:structure_content"

# `blocks` 里的取值带方块状态（`minecraft:grass_block{snowy:false}`），
# 注册表里是裸名。剥到第一个 `{` 或 `[`。
_STATE_SUFFIX = re.compile(r"[{\[].*$", re.S)


@dataclass
class BindingsCompileResult:
    rules: list[Rule] = field(default_factory=list)
    # 模板里出现但不在方块注册表的 id（对账不通过，留痕不静默）
    unknown_block_ids: Counter = field(default_factory=Counter)
    # 模板方块里已经有其它来源规则的 head 数（仅统计，不影响是否发规则）
    already_seeded: int = 0
    template_blocks: int = 0
    # 结构刷怪里实体不在 entity 注册表的条目
    unknown_entities: Counter = field(default_factory=Counter)
    spawned_entities: int = 0
    # 模板 NBT 里直接写着的实体（村民、猫、铁傀儡…）
    template_entities: int = 0
    # 模板方块实体里装着的物品：绑定数、不属物品注册表的 id、方块实体类型不是方块名
    template_items: int = 0
    unknown_item_ids: Counter = field(default_factory=Counter)
    unknown_item_holders: Counter = field(default_factory=Counter)


def _bare_block(state: str) -> str:
    return _STATE_SUFFIX.sub("", state).strip()


def _structure_node(ident: str) -> str | None:
    """结构事实 id → `structure:<命名空间>:<名>`。

    两种来源的 id 形态不同：

    - 数据包：`src/main/resources/data/<ns>/worldgen/structure/<名>`
    - 运行期导出：`configured_structure_feature/<名>`（1.18.2 的 reports 全是原版命名空间）

    数据包形态能直接读出命名空间，优先。取不到时退回 `<末段>` 并假定 `minecraft:`——
    运行期导出只含原版注册成功的条目，这个假定有依据，但要让调用方知道是假定的。
    """
    match = re.search(r"data/([^/]+)/worldgen/[^/]+/(.+)$", ident)
    if match is not None:
        namespace, local = match.group(1), match.group(2)
        return node("structure", f"{namespace}:{local}")
    if "/" not in ident:
        return None
    local = ident.rsplit("/", 1)[-1]
    if not local:
        return None
    return node("structure", f"minecraft:{local}")


def compile_bindings(
    template_facts: list[Fact],
    worldgen_facts: list[Fact],
    block_ids: set[str],
    entity_ids: set[str],
    item_ids: set[str],
    existing_heads: set[str],
    spawner_facts: list[Fact] | None = None,
) -> BindingsCompileResult:
    """模板方块、结构刷怪、试炼刷怪笼 → `seeds` / `spawns` 规则。

    `existing_heads` 用来避免重复点亮同一个节点：世界生成可能已经给
    `block:X` 或 `structure:Y` 发过规则，重复发只会让规则数虚高。
    `spawner_facts` 是 `trial_spawner` 注册表（`spawner_config` 事实）。
    """
    result = BindingsCompileResult()

    # ---- 一、模板里的方块 ----
    #
    # 同一个方块会出现在几十个模板里，只发一条规则；meta 记前几个模板，
    # 够人回溯，不把几十个文件名塞进 meta。
    evidence: dict[str, list[str]] = {}
    for fact in template_facts:
        for state in fact.payload.get("blocks") or []:
            if not isinstance(state, str):
                continue
            bare = _bare_block(state)
            if not bare:
                continue
            if bare not in block_ids:
                result.unknown_block_ids[bare] += 1
                continue
            if bare in evidence:
                if len(evidence[bare]) < 3:
                    evidence[bare].append(fact.prov.file)
                continue
            evidence[bare] = [fact.prov.file]

    result.template_blocks = len(evidence)
    for ident in sorted(evidence):
        head = node("block", ident)
        if head in existing_heads:
            # 已有别的来源给过这个方块规则（世界生成、变换、放置桥）。
            # **仍然要发**：同 head 多规则就是 OR，这是新增一条获取路径；
            # 跳过会让「有其他路径但都走不通」的方块彻底失去模板这条腿。
            result.already_seeded += 1
        result.rules.append(
            Rule(
                id=f"binding:template-block:{ident}",
                head=head,
                body=(DEFAULT_WORLD,),
                kind="seeds",
                family=f"{FAMILY}/template_block",
                meta={
                    "basis": "出现在结构模板里；模板只作为结构的一部分生成",
                    "templates": evidence[ident],
                },
            )
        )

    # ---- 二、结构刷怪配置 ----
    for fact in worldgen_facts:
        payload = fact.payload
        if payload.get("worldgen_kind") not in ("structure", "configured_structure_feature"):
            continue
        raw = payload.get("spawns")
        if not raw:
            continue
        structure = _structure_node(str(payload.get("id") or ""))
        if structure is None:
            result.unknown_entities[f"<结构无法定位>:{payload.get('id')}"] += 1
            continue
        # 结构节点同理：已经有 `← world` 就直接用，没有才补。
        # 刷怪规则的 body 需要这个节点成立，重复发虽无害但没必要。
        if structure not in existing_heads:
            result.rules.append(
                Rule(
                    id=f"binding:structure:{structure}",
                    head=structure,
                    body=(DEFAULT_WORLD,),
                    kind="seeds",
                    family=f"{FAMILY}/structure",
                    meta={"basis": "结构 JSON 定义了刷怪配置", "file": fact.prov.file},
                    prov=fact.prov,
                )
            )
            existing_heads.add(structure)

        for index, spawn in enumerate(raw):
            if not isinstance(spawn, dict):
                continue
            ident = spawn.get("entity")
            if not isinstance(ident, str):
                continue
            if ident not in entity_ids:
                result.unknown_entities[ident] += 1
                continue
            result.spawned_entities += 1
            result.rules.append(
                Rule(
                    id=f"binding:spawn:{structure}:{ident}:{index}",
                    head=node("entity", ident),
                    body=(structure,),
                    kind="spawns",
                    family=f"{FAMILY}/spawn",
                    meta={
                        "basis": "结构的 spawn_overrides",
                        "category": spawn.get("category"),
                    },
                    prov=fact.prov,
                )
            )

    # ---- 三、模板里直接写着的实体 ----
    #
    # `village/plains/houses/plains_library_1.snbt` 的 NBT 里有
    # `entities: [{id: "minecraft:villager", has_equipment: true, …}]`。
    # 这是村民**唯一**的数据包踪迹：村民不由任何生物群系的刷怪表生成
    # （`spawners` 里没有它），也不由任何配方产出。
    #
    # 不读它，`entity:minecraft:villager` 在两个版本都是零规则、状态 FALSE，
    # 于是所有以村民为前提的机制一起断链：交易（364 条规则）在 1.18.2 恒假，
    # 附魔书与藏宝图因此一律不可达。这个错误不报任何错，只表现为可达性偏低。
    #
    # 用 `world:` 而不是具体结构：模板事实只给模板路径，不含它属于哪个结构，
    # 硬推一个结构 ID 会造出不存在的节点。与「模板里的方块」同一处理，
    # 因为两者都是「模板里有这个东西 → 结构生成它」。
    template_entities: dict[str, list[str]] = {}
    for fact in template_facts:
        for entry in fact.payload.get("entities") or []:
            if not isinstance(entry, dict):
                continue
            ident = entry.get("id")
            if not isinstance(ident, str):
                continue
            if ident not in entity_ids:
                # 模板的 `entities` 里也会有非实体 id（26.3 的 `minecraft:cushion`
                # 是方块实体）。不静默跳过：留痕后由报告指出。
                result.unknown_entities[ident] += 1
                continue
            template_entities.setdefault(ident, [])
            if len(template_entities[ident]) < 3:
                template_entities[ident].append(fact.prov.file)

    for ident in sorted(template_entities):
        result.template_entities += 1
        result.rules.append(
            Rule(
                id=f"binding:template-entity:{ident}",
                head=node("entity", ident),
                body=(DEFAULT_WORLD,),
                kind="seeds",
                family=f"{FAMILY}/template_entity",
                meta={
                    "basis": "模板 NBT 里含该实体；模板作为结构的一部分生成",
                    "templates": template_entities[ident],
                },
            )
        )

    # ---- 四、模板方块实体里装着的物品 ----
    #
    # `trial_chambers/decor/flow_pot.snbt` 的饰纹陶罐带
    # `nbt: {sherds: {back: {id: "minecraft:flow_pottery_sherd"}, ...}}`。
    # 挖掉这个陶罐就得到那个陶片——这是该物品在数据包里的**唯一**踪迹：
    # 它不在任何战利品表里，也不由任何配方产出。
    #
    # `holder` 是承载的方块实体类型（`minecraft:decorated_pot`）。绑定到
    # `block:` 而不是 `world:`，因为陶罐本身要有来源：它由模板方块桥接保证，
    # 而模板方块又接到 `world:`。多绕一层能让「这是什么方块给的」留在证明链上。
    items_by_holder: dict[tuple[str, str], list[str]] = {}
    for fact in template_facts:
        for ref in fact.payload.get("item_refs") or []:
            if not isinstance(ref, dict):
                continue
            holder = ref.get("holder")
            ident = ref.get("id")
            if not isinstance(holder, str) or not isinstance(ident, str):
                continue
            if ident not in item_ids:
                result.unknown_item_ids[ident] += 1
                continue
            items_by_holder.setdefault((holder, ident), []).append(fact.prov.file)

    for (holder, ident), files in sorted(items_by_holder.items()):
        if holder not in block_ids:
            # 方块实体类型名不一定是方块名（`minecraft:skull` ↔ `skeleton_skull`），
            # 对不上的留痕，不拼一个可能不存在的 block 节点
            result.unknown_item_holders[holder] += 1
            continue
        result.template_items += 1
        result.rules.append(
            Rule(
                id=f"binding:template-item:{holder}:{ident}",
                head=node("item", ident),
                body=(node("block", holder),),
                kind="yield",
                family=f"{FAMILY}/template_item",
                meta={
                    "basis": "模板里的方块实体带该物品；拆掉方块即得",
                    "holder": holder,
                    "templates": files[:3],
                },
            )
        )

    # ---- 四、试炼刷怪笼的实体 ----
    #
    # `structure:trial_chambers` 的 `spawn_overrides` 是空数组：试炼密室的怪物
    # 全部来自刷怪笼，走 `data/<ns>/trial_spawner/**` 这份注册表。
    # 不读它，`breeze` 就不存在于任何事实里，`breeze_rod` 与 `mace` 因此断链。
    #
    # 用假设节点而不是 `structure:trial_chambers`：配置目录名（`trial_chamber`）
    # 与结构 ID（`trial_chambers`）之间没有可复算的映射，硬推一个只会造出
    # 指向不存在结构的节点。语义上「刷怪笼在结构里、结构内容可取得」正对
    # `assume:structure_content`，与 `structure_entities` 那条 idiom 同级。
    for fact in spawner_facts or []:
        payload = fact.payload
        ident = payload.get("id")
        for index, entry in enumerate(payload.get("entities") or []):
            if not isinstance(entry, dict):
                continue
            entity = entry.get("id")
            if not isinstance(entity, str):
                continue
            if entity not in entity_ids:
                result.unknown_entities[entity] += 1
                continue
            result.spawned_entities += 1
            result.rules.append(
                Rule(
                    id=f"binding:spawner:{ident}:{entity}:{index}",
                    head=node("entity", entity),
                    body=(SPAWNED_CONTENT,),
                    kind="spawns",
                    family=f"{FAMILY}/spawner",
                    meta={
                        "basis": "试炼刷怪笼配置",
                        "config": ident,
                        "tier": payload.get("tier"),
                    },
                    prov=fact.prov,
                )
            )

    return result
