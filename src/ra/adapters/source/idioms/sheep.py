"""idiom：羊剪毛的颜色 → 羊毛映射。

两版形态完全不同，但语义相同：

| 版本 | 形态 | 事实来源 |
|---|---|---|
| 1.18.2 | `ITEM_BY_DYE` 静态 Map + `spawnAtLocation` | 只能从代码抽 |
| 26.3 | `dropFromShearingLootTable(SHEAR_SHEEP, ...)` | 表在数据包，只需 `holds` |

因此本 idiom 在 26.3 只产出 `holds`（羊 → 剪毛表），在 1.18.2 产出完整的 `yield`。

**等价性**：1.18.2 抽出的 16 条 `white_wool ← sheep + shears` 应当与 26.3
数据包 `shearing/sheep/white.json` 的同名事实重合。这由集成测试断言。

**软约束**：`flag:sheep/color=<色>` 与 `flag:sheep/unsheared` 只缩小可行域，不参与判定——
羊剪一次后仍是那只羊，不能因为「已剪毛」判成不可获取。

排序名用 `flag`（「特性开关」）：羊的颜色与剪毛状态是布尔的
世界状态事实，不是物品/方块/实体中的任何一种。早先这些节点写作 `state:`，
而 `state` 不在 §4.2 的固定集合内，于是 1.18.2 的 IR 编译直接抛
`节点格式不合法`——整版跑不起来，26.3 因为走数据包表根本没碰到这条路径。
"""

from __future__ import annotations

import re

from ....facts import Fact
from ..index import JavaIndex
from ..lootconstants import LootConstants, parse_builtin_loot_tables
from .base import Idiom, IdiomResult, Link

ID = "sheep_shear"

# 颜色 → 羊毛物品名由代码里的注册名给出，不写清单。
# `Blocks.WHITE_WOOL` → `white_wool`
PUT_PATTERN = re.compile(
    r"\.put\(\s*DyeColor\.([A-Z_]+)\s*,\s*(?:Blocks|Items)\.([A-Z][A-Z0-9_]*)\s*\)"
)
SHEARING_TABLE_CALL = re.compile(
    r"dropFromShearingLootTable\s*\([^;]*?BuiltInLootTables\.([A-Z][A-Z0-9_]*)"
)
COUNT_PATTERN = re.compile(r"(\d+)\s*\+\s*\w+\.random\.nextInt\(\s*(\d+)\s*\)")
SHEARS_GATE = re.compile(r"\.is\(\s*Items\.SHEARS\s*\)")

# 26.x 的颜色分发：`SHEAR_DYED_SHEEP` 这类按颜色集合展开的常量
DYED_CONSTANT = re.compile(r"BuiltInLootTables\.([A-Z][A-Z0-9_]*DYED[A-Z0-9_]*)")
SHEEP_COMPONENT = re.compile(r"DataComponents\.SHEEP_COLOR")

WOOL_SUFFIX = "_wool"


class SheepShear(Idiom):
    id = ID
    needs = ("shearing_table",)
    min_hits = 1

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        constants = parse_builtin_loot_tables(index)

        targets = index.find_path_contains("/Sheep.java")
        if not targets:
            result.note("未找到 Sheep.java，剪毛路径将缺失")
            return result

        handled = False
        for java in targets:
            if self._modern(java, constants, result):
                handled = True
            if self._legacy(java, result):
                handled = True

        if not handled:
            result.note(
                "Sheep.java 里两种剪毛形态都没识别到；"
                "若该版本改了实现，需新增 idiom 或登记人工例外"
            )
        return result

    # ---- 26.x：单张分发表 + 按颜色展开的子表 ---------------------------

    def _modern(self, java, constants: LootConstants, result: IdiomResult) -> bool:
        match = SHEARING_TABLE_CALL.search(java.text)
        if match is None:
            return False

        constant = match.group(1)
        table_ids = constants.expand(constant)
        if not table_ids:
            result.note(
                f"{java.path}: 引用了 BuiltInLootTables.{constant}，"
                "但常量表里查不到它的注册路径（可能解析器未覆盖该写法）"
            )
            return False

        for table_id in table_ids:
            result.add(
                Link(
                    head=f"table:{table_id}",
                    kind="holds",
                    via=("entity:minecraft:sheep",),
                    meta={
                        "table_constant": constant,
                        "carrier": "sheep/shear",
                        "table_count": len(table_ids),
                    },
                ),
                ID,
                java.path,
                f"Sheep#shear -> {constant}",
            )

        # 颜色分发：26.x 把 16 张子表交给数据包（datagen 生成），运行时只引用入口表。
        # 子表本身由 loot_table 事实覆盖，code_link 不重复记录，但要说明这层关系。
        dyed = DYED_CONSTANT.search(java.text)
        if dyed is not None and dyed.group(1) != constant:
            sub_ids = constants.expand(dyed.group(1))
            if sub_ids:
                result.note(
                    f"{java.path}: 颜色分发走 {dyed.group(1)}（{len(sub_ids)} 张子表），"
                    f"入口表 {constant} 只负责分发；子表内容由数据包事实提供"
                )
        if SHEEP_COMPONENT.search(java.text):
            result.note(
                f"{java.path}: 羊的颜色由 DataComponents.SHEEP_COLOR 承载，"
                "颜色维度的选择属 IR 变体规则，不在 code_link 判定"
            )
        return True

    # ---- 1.18.x：静态映射 + spawnAtLocation ---------------------------

    def _legacy(self, java, result: IdiomResult) -> bool:
        pairs = PUT_PATTERN.findall(java.text)
        if not pairs:
            return False

        if not SHEARS_GATE.search(java.text):
            result.note(f"{java.path}: 有颜色映射但没找到剪刀判断，工具前置记 UNKNOWN")
        # 节点名必须带命名空间：`bridge/tool` 产出的是 `tool:minecraft:shears`，
        # 写成 `tool:shears` 会是另一个永远不成立的节点，于是整条剪毛规则恒假。
        # 26.3 走数据包表不产这条规则，所以只有 1.18.2 会暴露。
        tool_nodes = ("tool:minecraft:shears",) if SHEARS_GATE.search(java.text) else ()

        count_min, count_max = 1, 1
        counts = COUNT_PATTERN.search(java.text)
        if counts is not None:
            count_min = int(counts.group(1))
            count_max = count_min + int(counts.group(2)) - 1

        produced = 0
        for color, ident in pairs:
            item = ident.lower()
            if not item.endswith(WOOL_SUFFIX):
                result.note(f"{java.path}: DyeColor.{color} 对应 {item}，不是羊毛，跳过")
                continue
            result.add(
                Link(
                    head=f"item:minecraft:{item}",
                    kind="yield",
                    via=("entity:minecraft:sheep",),
                    inputs=tool_nodes,
                    soft=(f"flag:sheep/color={color.lower()}", "flag:sheep/unsheared"),
                    meta={"count": {"min": count_min, "max": count_max}},
                ),
                ID,
                java.path,
                "Sheep#shear -> ITEM_BY_DYE",
            )
            produced += 1

        if produced == 0:
            result.note(f"{java.path}: 颜色映射里没有羊毛条目")
            return False

        result.note(f"{java.path}: 从静态映射抽出 {produced} 条剪毛产出（1.18 形态）")
        return True


def exported() -> list[Idiom]:
    return [SheepShear()]
