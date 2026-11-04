"""配方 → `yield` 规则。

一条配方一条规则：`head` 是产物，`body` 是原料 + 设备。

## 原料的三种写法，统一归一

适配器已经把三种写法还原成同一形状 `{items: [...], tags: [...]}`：

```jsonc
"ingredients": [ {...}, {...} ]      // 无形状配方、切石、熔炼
"key":         { "#": {...} }        // 有形状配方
"extra":       { "base": {...} }     // 锻造、酿造等把原料放在 extra 里
```

所以这里不看 serializer 决定「原料在哪」，而是**递归找所有 `{items, tags}` 形状的值**。
新增 serializer 若沿用这个形状就能自动兼容，不需要在这里加分支。

## `#tag` 与具体物品

`tags: ["#minecraft:planks"]` 表示「任意木板」。编译成 `tag:item/minecraft:planks` 节点，
由 bridges 展开成 `implies` 规则。**OR 在 tag 节点的多条 implies 里表达**，
不在这里展开成多条规则——否则一条配方的 body 会爆炸成十几个备选。

## 设备

`serializer` → 设备由 `knowledge/maps/vocabulary/serializer_station.json` 给出。
表里没有的 serializer 即硬失败（未登记的条件类型 → 编译期硬失败并列台账，
不静默丢弃）。**不静默当成「无需设备」**——那会把需要熔炉的物品判成可徒手获得。

2x2 以内的有形状配方不需要工作台；超出的需要。判据是 `pattern` 的宽高，
不是 serializer 名字。
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Iterator

from ...facts import Fact
from ..nodes import Rule, node, tag_node

FAMILY = "recipes"

# `crafting_shaped` 的图案尺寸上限：2x2 以内用手工合成栏，超出需要工作台。
HAND_GRID = 2


def _iter_ingredient_like(value: object) -> Iterator[dict]:
    """递归找出所有 `{items, tags}` 形状的对象。

    `items` 与 `tags` 至少有一个存在才算，避免把恰好同名的别的字段当原料。
    """
    if isinstance(value, dict):
        if "items" in value or "tags" in value:
            yield value
        for sub in value.values():
            yield from _iter_ingredient_like(sub)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_ingredient_like(item)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def ingredient_slots(payload: dict) -> list[list[str]]:
    """配方 → 槽位列表。每槽是可接受的节点名（`#` 前缀表示 tag）。

    ## 槽位内是 OR，槽位之间是 AND

    这是本文件最容易搞错的一处，也是实测踩过的真 bug：

    ```jsonc
    // gold_nugget_from_smelting.json —— 熔炉只有一个输入槽
    "ingredients": [{"items": ["golden_pickaxe", "golden_shovel", … 12 个"]}]
    // sandstone_slab.json —— 一个槽位接受两种砂岩
    "key": [{"items": ["sandstone", "chiseled_sandstone"], "symbol": "#"}]
    ```

    一个槽位只能放一样东西，所以槽内的多个物品是**任选其一**。早先把
    `items` 平铺进 body，等于说「必须同时持有 12 件金装备才能烧出一粒金粒」——
    可达性会误判，图上也会出现一个 body 塞着 12 个原料的畸形菱形。用户看到的
    「金粒的烧炼配方很乱」就是这个。

    IR 的 body 是 AND，没有槽位内 OR 的位置，所以调用方按槽位展开成多条规则
    （见 `compile_recipes`）。实测量级：26.3 共 295 条配方有多选槽位（14%），
    展开后规则数 2042 → 3017，最大笛卡尔积 16，没有爆炸风险。
    """
    slots: list[list[str]] = []
    for blob in _iter_ingredient_like(
        {k: v for k, v in payload.items() if k != "result"}
    ):
        choices: list[str] = []
        for ident in blob.get("items") or []:
            if not isinstance(ident, str):
                continue
            # `items` 里也可能写 `#tag`，与 `tags` 字段同义
            choices.append(ident if ident.startswith("#") else ident)
        for ident in blob.get("tags") or []:
            if isinstance(ident, str):
                choices.append("#" + ident.lstrip("#"))
        if choices:
            slots.append(_dedupe(choices))
    return slots


def _slot_node(choice: str) -> str:
    """槽位里的一个选项 → 节点。`#` 前缀是标签，其余是物品。"""
    if choice.startswith("#"):
        return tag_node("minecraft:item", choice[1:])
    return node("item", choice)


def _pattern_needs_table(pattern: object) -> bool:
    """有形状配方的图案是否超出 2x2 手工合成栏。"""
    if not isinstance(pattern, list) or not pattern:
        return False
    height = len([row for row in pattern if isinstance(row, str)])
    width = max((len(row) for row in pattern if isinstance(row, str)), default=0)
    return height > HAND_GRID or width > HAND_GRID


class RecipeCompileResult:
    """编译产物 + 跳过项汇总。"""

    def __init__(self) -> None:
        self.rules: list[Rule] = []
        # 自指配方：产物本身是原料（如复制纹饰模板）。不是入口，不产规则。
        self.self_referential: list[str] = []
        # 无原料配方：不当成「徒手可得」，留给归因说明。
        self.no_ingredient: list[str] = []
        self.unknown_serializers: Counter = Counter()
        # 因槽位内多选而展开成多条规则的配方：(文件, 组合数, 实际条数)
        self.expanded: list[tuple[str, int, int]] = []


def compile_recipes(
    facts: list[Fact], stations: dict[str, str | None]
) -> RecipeCompileResult:
    """把 recipe 事实编译成规则。

    `stations` 是 `serializer → 设备 ID（或 None）`。缺键即硬失败。
    """
    result = RecipeCompileResult()

    for fact in facts:
        payload = fact.payload
        serializer = payload.get("serializer")
        if not isinstance(serializer, str):
            continue

        if serializer not in stations:
            result.unknown_serializers[serializer] += 1
            continue

        product = payload.get("result")
        if not isinstance(product, dict):
            continue
        product_id = product.get("id")
        if not isinstance(product_id, str) or not product_id:
            # `smithing_trim` 的 result 是 `{}`：不产新产物，只做变体
            continue

        head = node("item", product_id)

        station = stations[serializer]
        if station is None and _pattern_needs_table(payload.get("pattern")):
            # 图案超出 2x2，必须有工作台；表里写 null 是因为 2x2 也能做
            station = "minecraft:crafting_table"

        # 槽位之间 AND、槽位内 OR。IR 的 body 只有 AND，所以槽位内多选要
        # 展开成多条同 head 规则（详见 `ingredient_slots` 的说明）。
        slots = ingredient_slots(payload)
        if not slots:
            if station is None:
                result.no_ingredient.append(fact.prov.file)
                continue
            # 只有设备、没有原料：仍是一条规则（设备本身是可得的），
            # 交给归因，不当成「徒手可得」。
            combos: list[tuple[str, ...]] = [()]
        else:
            combos = list(itertools.product(*slots))

        emitted = 0
        seen_bodies: set[frozenset[str]] = set()
        for combo in combos:
            body = [_slot_node(choice) for choice in combo]
            if station is not None:
                body.append(node("station", station))

            if head in body:
                # 复制类配方（纹饰模板复制、竹筏变木筏这类）：
                # 产物本身是原料，对「首次可达」无贡献。若当成规则，会形成一个
                # body 含自身的环，让归因误报 cycle_no_entry。
                result.self_referential.append(fact.prov.file)
                break

            # 不同组合可能落到同一组节点上（同一物品占多个槽位时），去重
            key = frozenset(body)
            if key in seen_bodies:
                continue
            seen_bodies.add(key)

            result.rules.append(
                Rule(
                    # 单组合保持原 id；多组合加序号，否则同文件的多条规则撞 id。
                    id=(
                        f"recipe:{fact.prov.file}"
                        if len(combos) == 1
                        else f"recipe:{fact.prov.file}#{emitted}"
                    ),
                    head=head,
                    body=tuple(body),
                    kind="yield",
                    family=FAMILY,
                    meta={
                        "serializer": serializer,
                        "count": product.get("count", 1),
                    },
                    prov=fact.prov,
                )
            )
            emitted += 1

        if len(combos) > 1:
            result.expanded.append((fact.prov.file, len(combos), emitted))

    return result
