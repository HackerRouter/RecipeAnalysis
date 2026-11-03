"""idiom：猪灵以物易物（给金锭 → 战利品表）。

```java
// 26.3 / 1.18.2 net/minecraft/world/entity/monster/piglin/PiglinAi.java
public static final Item BARTERING_ITEM = Items.GOLD_INGOT;

LootTable lootTable = ...getLootTable(BuiltInLootTables.PIGLIN_BARTERING);
List<ItemStack> items = lootTable.getRandomItems(...);
```

以物易物是**转换**，不是「世界给你」：得先有金锭，换到什么由表决定。

## 为什么必须单列一条 idiom

`gameplay/piglin_bartering` 原先由 `table_providers.json` 的 `gameplay` 目录约定
统一挂到 `assume:player`（「钓鱼、以物易物、晨礼等玩家动作触发」）。这个粒度把
五种互不相干的东西糊成一个前提，代价在图上看得见：黑曜石的来源标签写成
`玩法 · piglin_bartering`，读者无从知道它要金锭，也看不出这是一次交易。

代码里付款物是写明的（`BARTERING_ITEM`），没有任何猜测成分。抽出来之后
`table:gameplay/piglin_bartering ← item:minecraft:gold_ingot`，
与村民交易同构：付款物进 `inputs`，必须递归求可达。

## 与 `trades` idiom 的分工

`trades` 抽的是 `VillagerTrades` / 数据包 `villager_trade`——那是有职业、有等级、
可补货的定价表。猪灵以物易物没有职业也没有等级，付款物是单一常量、产出是概率表，
形态不同，所以不并进 `trades`。

## 判据

1. 文件是 `PiglinAi.java`
2. 有 `BARTERING_ITEM = Items.<常量>`
3. 全文出现 `PIGLIN_BARTERING`

三者同时成立才产规则。缺任一条留一条 note，不静默跳过。
"""

from __future__ import annotations

import re

from ..index import JavaFile, JavaIndex
from .base import Idiom, IdiomResult, Link

ID = "piglin_barter"

# 付款物：`public static final Item BARTERING_ITEM = Items.GOLD_INGOT;`
PAYMENT = re.compile(
    r"BARTERING_ITEM\s*=\s*Items\.([A-Z][A-Z0-9_]*)"
)

# 产出表由 `BuiltInLootTables` 的常量间接给出（值见同名类：
# `PIGLIN_BARTERING = register("gameplay/piglin_bartering")`）。
# 这里只认出现，表 ID 按注册名硬写：常量→路径的映射在 BuiltInLootTables 里，
# 而那份映射随版本变（1.18.2 用 `LootTables` 类），跨类解析容易静默取错。
LOOT_TABLE_CONST = "PIGLIN_BARTERING"
TABLE_NODE = "table:minecraft:gameplay/piglin_bartering"


def _is_piglin_ai(path: str) -> bool:
    return path.rsplit("/", 1)[-1] == "PiglinAi.java"


class PiglinBarter(Idiom):
    id = ID
    needs = ("piglin_bartering_item", "piglin_bartering_table")
    # 两版各 1 条。0 命中说明措辞变了，必须硬失败而不是悄悄不出规则。
    min_hits = 1

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        found = False
        for java in index.files.values():
            if not _is_piglin_ai(java.path):
                continue
            found = True
            self._file(java, result)
        if not found:
            result.note("未找到 PiglinAi.java，猪灵以物易物无代码来源")
        return result

    def _file(self, java: JavaFile, result: IdiomResult) -> None:
        payment = PAYMENT.search(java.text)
        if payment is None:
            result.note(f"{java.path}: 找不到 BARTERING_ITEM 的付款物常量")
            return
        if LOOT_TABLE_CONST not in java.text:
            result.note(
                f"{java.path}: 找不到 {LOOT_TABLE_CONST}，猪灵交易的产出表无法接上"
            )
            return

        item = payment.group(1).lower()
        result.add(
            Link(
                head=TABLE_NODE,
                kind="holds",
                # 金锭是消耗品：给出去就不在手里了，必须递归求可达
                inputs=(f"item:minecraft:{item}",),
                meta={
                    "basis": f"PiglinAi.BARTERING_ITEM = Items.{payment.group(1)}",
                    "loot_table": LOOT_TABLE_CONST,
                },
            ),
            ID,
            java.path,
            "PiglinAi#BARTERING_ITEM -> BuiltInLootTables.PIGLIN_BARTERING",
        )
        result.note(
            f"{java.path}: 猪灵交易 {item} → {TABLE_NODE}（付款物进 inputs）"
        )


def exported() -> list[Idiom]:
    return [PiglinBarter()]
