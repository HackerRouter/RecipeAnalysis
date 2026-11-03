"""工具能力桥接：方块要求什么工具才能掉东西。

## 为什么需要它

战利品表只说「掉什么」，从不说「用什么挖」。`blocks/emerald_ore` 的 JSON 里
没有任何工具条件——「绿宝石矿要铁镐」是**方块属性**，写在物品的工具组件里。
不接这一层，`item:emerald` 的路径就是「世界里有矿 → 掉绿宝石」，
少了整条工具链，读者会以为徒手能挖。

## 数据在哪，为什么不写知识表

两个事实直接给全，无需等级数字、无需材质清单：

1. **物品的 `minecraft:tool` 组件**——每个工具物品带着自己的规则：

   ```jsonc
   "minecraft:tool": {"rules": [
     {"blocks": "#minecraft:incorrect_for_iron_tool", "correct_for_drops": false},
     {"blocks": "#minecraft:mineable/pickaxe",          "correct_for_drops": true, "speed": 6.0}
   ]}
   ```

2. **`incorrect_for_*_tool` 方块标签**——用嵌套表达等级，不是数字：

   ```
   incorrect_for_wooden_tool ⊇ [needs_diamond, needs_iron, needs_stone]
   incorrect_for_stone_tool  ⊇ [needs_diamond, needs_iron]
   incorrect_for_iron_tool   ⊇ [needs_diamond]
   incorrect_for_diamond_tool ⊇ []
   ```

于是「物品 I 能采方块 B 并获掉落」= `B ∈ allows(I) 且 B ∉ denies(I)`，
全部由事实推出。**不写等级表、不写材质清单**——那会随版本漂移
（26.3 有铜工具，1.18.2 没有）。

## 为什么取最弱的一档

合格工具往往有多个（绿宝石矿：铁/钻石/下界合金镐）。若把每个都编成一条
`block` 规则，规则数按「方块 × 工具」增长；更重要的是图上会显示三条并列
的镐子，读者无法判断「至少要什么」。

「A 比 B 弱」可直接从数据判定：`denies(A) ⊇ denies(B)`（不能挖的更多即更弱）。
留下拒绝集**最大**的那些工具即最弱集。绿宝石矿因此只留铁镐，
黑曜石留钻石与下界合金（两者拒绝集都空，不可比，都保留）。

这不改变可达性结论（更高级工具总是可由低级工具链得出），只让路径说清楚
「最低门槛」。

## 只对「必须用正确工具才掉」的方块生效

方块分两种：泥土徒手也能掉，石头必须用镐。后者的标记（
`requiresCorrectToolForDrops`）不在 `blocks.json` 报告里，也不是任何事实，
所以无法直接读。

可用的判据是：**方块是否出现在某个 `incorrect_for_*_tool` 标签里**。
这些标签的成员就是 `needs_stone/iron/diamond_tool` 三张标签（94 个方块）。

- 在里面的：必须用一档够用的工具，工具要求成立
- 不在里面的：用什么都行（或徒手），工具要求不适用

这一取舍会少报「石头需要任意镐」这类要求（石头不在三张 needs 标签里），
但**绝不会误报**——给叶片强加锄头要求会让路径凭空多一道工序。宁可少说。

## 节点形状

`tool:minecraft:iron_pickaxe`——沿用 `tool` 排序。它与 `tool:minecraft:pickaxe`
（工具类）不是一回事：后者是「任意一把镐」，前者是「具体这一把」。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ...facts import Fact
from ..nodes import Rule, node
from ..tags import TagMembers

FAMILY = "bridge/harvest"


@dataclass
class HarvestResult:
    """推导结果。"""

    # 方块 id（不带排序前缀）→ 最弱合格工具节点
    capabilities: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # 有工具组件但既无 allows 也无 denies 的物品（形状异常，留痕）
    unreadable_tools: list[str] = field(default_factory=list)
    # 工具组件里引用了查不到的标签
    unresolved_refs: dict[str, int] = field(default_factory=dict)
    # 方块数 / 工具数，供台账
    blocks: int = 0
    tools: int = 0


def _members(ref: str, registry: str, tags: TagMembers) -> set[str] | None:
    """`#minecraft:mineable/pickaxe` / `minecraft:cobweb` → 成员集合。

    `#` 后的 tag 名**带命名空间**，那是 `TagMembers` 的键。
    标签查不到时返回 `None`，让调用方留痕而不是当成空集。
    """
    if ref.startswith("#"):
        tag_id = ref[1:]
        if not tags.has(registry, tag_id):
            return None
        return tags.members(registry, tag_id)
    return {ref}


def derive_capabilities(
    component_facts: list[Fact], tags: TagMembers
) -> HarvestResult:
    """从物品的工具组件推「方块 → 最弱合格工具」。"""
    result = HarvestResult()

    allows: dict[str, set[str]] = {}
    denies: dict[str, set[str]] = {}
    for fact in component_facts:
        item = fact.payload.get("item")
        components = fact.payload.get("components")
        if not isinstance(item, str) or not isinstance(components, dict):
            continue
        tool = components.get("minecraft:tool")
        if not isinstance(tool, dict):
            continue
        allow: set[str] = set()
        deny: set[str] = set()
        for raw in tool.get("rules") or []:
            if not isinstance(raw, dict):
                continue
            ref = raw.get("blocks")
            if not isinstance(ref, str):
                continue
            members = _members(ref, "minecraft:block", tags)
            if members is None:
                result.unresolved_refs[ref] += 1
                continue
            target = allow if raw.get("correct_for_drops") is True else deny
            target |= members
        if not allow and not deny:
            result.unreadable_tools.append(item)
            continue
        allows[item] = allow
        denies[item] = deny

    result.tools = len(allows)

    # 必须用正确工具才掉落的方块 = incorrect_for_* 标签的并集。
    # 不在里面的方块徒手也能掉，不该被加上工具要求。
    requires_correct = set()
    for ref in (
        "#minecraft:incorrect_for_wooden_tool",
        "#minecraft:incorrect_for_stone_tool",
        "#minecraft:incorrect_for_copper_tool",
        "#minecraft:incorrect_for_iron_tool",
        "#minecraft:incorrect_for_gold_tool",
        "#minecraft:incorrect_for_diamond_tool",
        "#minecraft:incorrect_for_netherite_tool",
    ):
        members = _members(ref, "minecraft:block", tags)
        if members:
            requires_correct |= members

    # 反向索引：方块 → 合格工具（只保留需要工具的那批方块）
    harvestable: dict[str, set[str]] = defaultdict(set)
    for item, allow in allows.items():
        for block in (allow - denies[item]) & requires_correct:
            harvestable[block].add(item)

    for block, tools in harvestable.items():
        # 只留「最弱」的一档：拒绝集最大者。拒绝集相同即互为等价，都保留。
        widest = max(len(denies[item]) for item in tools)
        weakest = sorted(
            item for item in tools if len(denies[item]) == widest
        )
        result.capabilities[block] = tuple(node("tool", item) for item in weakest)

    result.blocks = len(result.capabilities)
    return result


def harvest_rules(result: HarvestResult) -> list[Rule]:
    """`tool:<物品> ← item:<物品>`。

    工具要求是具体物品，但节点用 `tool` 排序，好让图能把「作业条件」
    与「原料」分开画。这条规则把这层对应关系补上，否则工具节点恒假。
    """
    rules: list[Rule] = []
    seen: set[str] = set()
    for tools in result.capabilities.values():
        for tool_node in tools:
            if tool_node in seen:
                continue
            seen.add(tool_node)
            ident = tool_node.split(":", 1)[1]
            rules.append(
                Rule(
                    id=f"bridge:harvest:{ident}",
                    head=tool_node,
                    body=(node("item", ident),),
                    kind="implies",
                    family=FAMILY,
                    meta={"basis": "工具物品的 minecraft:tool 组件"},
                )
            )
    return rules
