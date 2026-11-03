"""词汇桥接：把标签、工具类别、设备、附魔变成规则。

## tag 为什么是 OR

`tag:item/minecraft:planks` 成立当且仅当任意一个成员成立。规则形状是：

```
tag:item/minecraft:planks  ←implies←  item:minecraft:oak_planks
tag:item/minecraft:planks  ←implies←  item:minecraft:spruce_planks
...
```

同一 `head` 多条规则即 OR。这也是「OR 由多条同 head 规则表达」这条设计的直接用例。

## station 的前提是物品

`station:minecraft:furnace` 不能凭空为真——玩家得先造出熔炉。所以：

```
station:minecraft:furnace  ←implies←  item:minecraft:furnace
```

数据包里没有「设备→物品」的显式表，但命名一致是本项目观察到的事实
（`furnace` 方块 ↔ `furnace` 物品），且**对账可验**：station 表里出现的每个设备
都必须在物品注册表里，否则记台账。约定失效时不会静默通过。

## 依据

- `tool_rules` 读 `knowledge/maps/vocabulary/tool_class`
- `station_rules` 读 `knowledge/maps/vocabulary/serializer_station`
- `tag_rules` 与 `enchant_rules` 不读知识表，纯粹按事实与词汇构造
"""

from __future__ import annotations

from ...facts import Fact
from ..nodes import Rule, RuleSet, node, registry_sort, tag_node

__all__ = ["enchant_rules", "station_rules", "tag_rules", "tool_rules"]


def tag_rules(tag_facts: list[Fact]) -> list[Rule]:
    """`tag:item/X` 的每个成员一条 `implies`。

    事实层已经把成员拆成两个字段：`values` 是直接条目，`nested` 是嵌套 tag
    引用（源的 `#` 前缀在适配器里剥掉了）。两边都要读——只读 `values` 会
    把「只有嵌套引用」的 tag（`logs`、`wooden_tool_materials` 这类聚合标签）
    当成空标签，于是整个只经聚合标签可达的配方线全部断掉，且断得无声无息。

    嵌套引用产 `tag ← tag` 规则，内层成立则外层成立。

    注册表认不出的 tag（biome、damage_type 等）不进 IR：它们的成员不是
    物品可达链上的节点，编进来只会造出永远为假的孤立节点。
    """
    rules: list[Rule] = []
    for fact in tag_facts:
        payload = fact.payload
        tag_id = payload.get("tag")
        registry = payload.get("registry")
        if not isinstance(tag_id, str) or not isinstance(registry, str):
            continue
        member_sort = registry_sort(registry)
        if member_sort is None:
            continue
        head = tag_node(registry, tag_id)
        short = registry.split(":", 1)[-1]

        pairs: list[tuple[str, str | None]] = []
        for member in payload.get("values") or []:
            ident = member if isinstance(member, str) else None
            if ident is None and isinstance(member, dict):
                ident = member.get("id")
            if isinstance(ident, str):
                pairs.append((ident, None))
        for ident in payload.get("nested") or []:
            if isinstance(ident, str):
                pairs.append((ident, "nested"))

        for index, (ident, origin) in enumerate(pairs):
            if origin is None and ident.startswith("#"):
                # 老格式的 `#` 前缀：适配器已在 `nested` 里剥掉，这里兜底
                body = tag_node(registry, ident[1:])
            elif origin == "nested":
                body = tag_node(registry, ident)
            else:
                body = node(member_sort, ident)
            rules.append(
                Rule(
                    # 同一 tag 名可能在不同注册表里都存在（如 block 与 item 都有
                    # `wither_immune_to`），所以 id 必须带注册表
                    id=f"bridge:tag:{short}:{tag_id}#{index}",
                    head=head,
                    body=(body,),
                    kind="implies",
                    family="bridge/tag",
                    meta={"registry": registry},
                    prov=fact.prov,
                )
            )
    return rules


def tool_rules(
    tool_classes: dict[str, str | None], item_ids: set[str]
) -> tuple[list[Rule], dict[str, int]]:
    """工具类 → 能充当该类的物品。

    两种形状：

    - 有物品标签的类（斧、锄、铲、镐、剑）：`tool:X ← tag:item/<标签>`。
      走标签而不是枚举物品——枚举会随版本漂移，也违反「不写清单」的纪律。
    - 单件工具（剪刀、刷子、打火石、水桶……）：工具 id 就是物品 id，
      写 `tool:X ← item:X`。它们没有物品标签（剪刀确实没有），
      但这不代表「只能由事实给」——那会让每条依赖剪刀的战利品规则全断。

    既没标签、物品注册表里也没有同名物品的类，记进 `missing` 由台账交代。
    """
    rules: list[Rule] = []
    missing: dict[str, int] = {}
    for tool_id, tag_id in tool_classes.items():
        if tag_id is None:
            if tool_id not in item_ids:
                missing[tool_id] = -1
                continue
            rules.append(
                Rule(
                    id=f"bridge:tool:{tool_id}",
                    head=node("tool", tool_id),
                    body=(node("item", tool_id),),
                    kind="implies",
                    family="bridge/tool",
                    meta={"singleton": True},
                )
            )
            continue
        rules.append(
            Rule(
                id=f"bridge:tool:{tool_id}",
                head=node("tool", tool_id),
                body=(tag_node("minecraft:item", tag_id),),
                kind="implies",
                family="bridge/tool",
                meta={"tag": tag_id},
            )
        )
    return rules, missing


def enchant_rules(rule_set: RuleSet, assumption: str = "assume:enchanting") -> list[Rule]:
    """`enchant:X ← assume:enchanting`。

    药水条件里的 `enchant:minecraft:silk_touch` 是硬前置：没有精准采集就挖不下
    这个方块。事实层只给出「需要某附魔」，怎么弄到附魔属假设层（有附魔台、
    青金石、经验即可），所以统一挂到 `assume:enchanting`。

    不做这层桥接的后果很隐蔽：`blocks/coal_ore` 表本身成立，只有附魔那一项
    恒假，于是矿石看起来「有表却拿不到」，归因还会指向表而不是附魔。
    """
    heads = {
        target
        for rule in rule_set.rules
        for target in rule.body
        if target.startswith("enchant:")
    }
    return [
        Rule(
            id=f"bridge:enchant:{head.partition(':')[2]}",
            head=head,
            body=(assumption,),
            kind="implies",
            family="bridge/enchant",
            meta={"basis": "假设玩家能进行附魔"},
        )
        for head in sorted(heads)
    ]


def station_rules(stations: list[str], item_ids: set[str]) -> tuple[list[Rule], list[str]]:
    """`station:X ← item:X`。返回 `(规则, 物品注册表里缺失的设备)`。

    约定是「设备名与物品名一致」。不一致时**不猜**：记进缺失清单，由台账交代。
    """
    rules: list[Rule] = []
    missing: list[str] = []
    for station in sorted(set(stations)):
        if station not in item_ids:
            missing.append(station)
            continue
        rules.append(
            Rule(
                id=f"bridge:station:{station}",
                head=node("station", station),
                body=(node("item", station),),
                kind="implies",
                family="bridge/station",
                meta={"basis": "设备名与物品名一致，且该物品在注册表里"},
                prov=None,
            )
        )
    return rules, missing
