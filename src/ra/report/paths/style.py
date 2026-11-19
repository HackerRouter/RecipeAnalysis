"""路径图的显示名与配色。

这里只做**翻译**：把规则自带的字段（`family`、`meta`）翻成人能读的类别名与
边文字，不新增判据、不读知识表、不猜。类别键全部来自事实里已有的取值，所以
「这个源属于哪一类」在任何版本上都能复算。

三处容易搞错的地方，都写在对应函数的文档字符串里：

1. `implies` 的语义随 head 排序变，边文字必须按 `(kind, head 排序)` 分开翻译。
2. 边方向一律「来源 → 产物」，中文里带「于」的写法会把方向说反。
3. 折叠压掉「一一对应」时，标签必须写出「N 组」。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ...ir.nodes import Rule, split_node

# 这些排序的节点是分析的起点，不再往上追问（与 solve/proof.py 一致）
ROOT_SORTS = frozenset({"assume", "world"})

# 起点的显示名。它们被吸进产物节点的标签（「主世界生成」「结构放置·village」），
# 所以名字必须短——一行标签里已经有两个词了。
WORLD_NAME = {
    "overworld": "主世界",
    "the_nether": "下界",
    "the_end": "末地",
}
ASSUME_NAME = {
    "player": "玩家",
    "time": "时间流逝",
    "crafting_table": "工作台",
    "furnace_fuel": "燃料",
    "water_source": "水源",
    "lava_source": "熔岩",
    "mob_spawn": "生物生成",
    "villager_trade": "村民交易",
    "wandering_trader": "流浪商人",
    "enchanting": "附魔",
    "structure_loot": "结构战利品",
    "structure_content": "结构内容",
    "end": "末地",
}

# 汉化边界
#
# | 汉化 | 内容 | 为什么 |
# |---|---|---|
# | ✓ | `WORLD_NAME` / `ASSUME_NAME` | 3 个维度、13 条假设，是注册表枚举 |
# | ✓ | `TABLE_KIND` / `LOOT_SOURCE` | 目录首段，实测 12 / 16 个 |
# | ✓ | `STATION_NAME` / `TOOL_NAME` / `ENCHANT_NAME` | 条件是固定枚举 |
# | ✗ | 结构名、战利品表名、物品 id | 由数据决定，无法穷举 |
#
# 后一类汉化不了的原因不是懒得写：「有的没汉化」必然发生——译名表要给几千个
# 表名逐条登记，少一条就是中英混排（`玩法 · cat_morning_gift · 试炼密室`），
# 而读者还得猜哪个是原名。统一用原名反而能直接对照数据包路径查证。
#
# 「放置」不是获取：`block ←item← ...` 反向指回物品，只会画出一个假环。
DROP_KINDS = frozenset({"places"})

# 作业条件，不是来源。它们与原料的区别只体现在画法上（虚线），
# 在 IR 里都是 body 成员（AND）。
CONDITION_PREFIXES = ("station:", "tool:", "enchant:")

# 条件的显示名。条件是「要什么」，用名词比 id 好读。
STATION_NAME = {
    "crafting_table": "工作台",
    "furnace": "熔炉",
    # 三种炉子归一到「熔炉」。源码里它们的 `RecipeType` 各不相同
    # （FurnaceBlockEntity → SMELTING、BlastFurnaceBlockEntity → BLASTING、
    # SmokerBlockEntity → SMOKING），但数据包里同一产物往往同时有 smelting 与
    # blasting 两个配方文件，原料产物完全一样。对「能不能拿到」而言两者是同一
    # 件事，图画成两个设备只是重复。IR 里仍保留真实清单，这里只改显示名。
    "blast_furnace": "熔炉",
    "smoker": "熔炉",
    "campfire": "营火",
    "stonecutter": "切石机",
    "brewing_stand": "造酿台",
    "smithing_table": "锻造台",
}
TOOL_NAME = {
    "wooden_pickaxe": "木镐",
    "stone_pickaxe": "石镐",
    "copper_pickaxe": "铜镐",
    "iron_pickaxe": "铁镐",
    "golden_pickaxe": "金镐",
    "diamond_pickaxe": "钻石镐",
    "netherite_pickaxe": "下界合金镐",
    "wooden_axe": "木斧",
    "stone_axe": "石斧",
    "copper_axe": "铜斧",
    "iron_axe": "铁斧",
    "golden_axe": "金斧",
    "diamond_axe": "钻石斧",
    "netherite_axe": "下界合金斧",
    "wooden_shovel": "木锹",
    "stone_shovel": "石锹",
    "copper_shovel": "铜锹",
    "iron_shovel": "铁锹",
    "golden_shovel": "金锹",
    "diamond_shovel": "钻石锹",
    "netherite_shovel": "下界合金锹",
    "wooden_hoe": "木锄",
    "stone_hoe": "石锄",
    "copper_hoe": "铜锄",
    "iron_hoe": "铁锄",
    "golden_hoe": "金锄",
    "diamond_hoe": "钻石锄",
    "netherite_hoe": "下界合金锄",
    "wooden_sword": "木剑",
    "stone_sword": "石剑",
    "copper_sword": "铜剑",
    "iron_sword": "铁剑",
    "golden_sword": "金剑",
    "diamond_sword": "钻石剑",
    "netherite_sword": "下界合金剑",
    "shears": "剪刀",
    "brush": "刷子",
}
ENCHANT_NAME = {
    "silk_touch": "精准采集",
    "fortune": "时运",
    "luck_of_the_sea": "海之眷顾",
}

# 战利品表首段 → 中文。假设类来源（`assume:structure_loot` 等）没有具体名字，
# 合并进表节点的标签里，否则每个表都会多一节「假设」。
TABLE_KIND = {
    "blocks": "方块",
    "chests": "宝箱",
    "archaeology": "考古",
    "pots": "陶罐",
    "barrels": "木桶",
    "entities": "生物",
    "gameplay": "玩法",
    "spawners": "刷怪笼",
    "shearing": "剪毛",
    "dispensers": "发射器",
    "equipment": "装备",
    "harvest": "收割",
    "brush": "刷扇",
    "carve": "雕刻",
    "till": "耕作",
}

# 战利品表路径首段 → 来源类别。键取自实测的 16 种首段。
LOOT_SOURCE = {
    "blocks": "挖掘方块",
    "chests": "结构战利品",
    "entities": "生物掉落",
    "gameplay": "玩法掉落",
    "archaeology": "考古",
    "spawners": "刷怪笼",
    "shearing": "剪毛",
    "barrels": "木桶",
    "dispensers": "发射器",
    "pots": "陶罐",
    "equipment": "生物装备",
    "charged_creeper": "高压爬行者",
    "harvest": "收割",
    "brush": "刷扫",
    "carve": "雕刻",
    "till": "耕地",
}

# 非合成的 serializer → 工艺名。合成类统一叫「合成」。
#
# 炉类三种（smelting / blasting / smoking）合并为「烧炼」：它们对应三个不同的
# `RecipeType`，但数据包里同一产物常同时有两种配方文件（原料与产物完全一样，
# 只是耗时与耗材不同）。不合并的话图上会出现「熔炼 · 12 条」与「高炉冶炼 · 12 条」
# 两条并列来源，读者会以为是两条不同的途径。
RECIPE_CRAFT = {
    "stonecutting": "切石",
    "brewing": "酿造",
    "smelting": "烧炼",
    "blasting": "烧炼",
    "smoking": "烧炼",
    # 营火不是炉子，也不接受上面三种配方类型，不并
    "campfire_cooking": "营火烹饪",
}

# bridge/* 子族的显示名
BRIDGE_NAME = {
    "tag": "标签成员",
    "table": "战利品表",
    "tool": "工具",
    "station": "工作站",
    "place": "放置",
    "enchant": "附魔",
    "convention": "约定变换",
    "entity_source": "实体来源",
    "entity_behaviour": "实体行为",
    "item_conversion": "物品转换",
    "harvest": "采集工具",
}

BINDINGS_NAME = {
    "template_block": "结构放置",
    "template_item": "结构藏物",
    "template_entity": "结构生成",
    "spawn": "结构生成",
    "spawner": "刷怪笼",
    "spawner_config": "刷怪笼",
}

# `code/*` 子族。合并进边后这些名字直接成为边文字，要能当动词读。
CODE_NAME = {
    "place_source": "放置",
    "structure_entities": "结构生成",
    "structure_gadgets": "结构装置",
    "mob_buckets": "生物桶",
    "fluid_buckets": "流体桶",
    "loot_alias": "战利品别名",
    "transform": "变换",
    "drops_source": "掉落",
    "sheep_shear": "剪毛",
    "death_drops": "死亡掉落",
    "interact_tables": "交互",
    # 1.18.x 的交易表硬编码在源码里，走 `code/*` 而不是 `trades` 族。
    # 不登记就会显示成「代码提取」，那是提取方式，不是来源。
    "villager_trades": "村民交易",
}

# 桶化时「这一类来源叫什么」。排序 → 中文；不是 IR 的一部分，只用于标签。
SOURCE_SORT_NAME = {
    "block": "方块",
    "item": "物品",
    "table": "战利品表",
    "entity": "实体",
    "world": "世界",
    "assume": "前提",
    "structure": "结构",
    "station": "设备",
    "tool": "工具",
    "enchant": "附魔",
    "templates": "模板",
}

# 规则 id 的首段 → 可读名。桶化时一堆 `rule::trade:…` 要能被认成「村民交易」，
# 否则只能叫「规则 · 10 条」，等于没说。
RULE_SOURCE_NAME = {
    "trade": "村民交易",
    "bridge": "标签成员",
    "loot": "战利品",
    "recipe": "配方",
    "worldgen": "生成",
    "binding": "结构内容",
}

# 节点填充色，按排序区分
FILL = {
    "item": "#dbeafe",
    "block": "#dcfce7",
    "entity": "#fef9c3",
    "tag": "#f3e8ff",
    "table": "#ffe4e6",
    "station": "#e0e7ff",
    "tool": "#ffedd5",
    "enchant": "#fae8ff",
    "structure": "#ccfbf1",
    "world": "#99f6e4",
    "assume": "#e2e8f0",
    "flag": "#f1f5f9",
    "template": "#fde68a",
    "rule": "#f8fafc",
    "group": "#eef2ff",
    "bucket": "#e2e8f0",
    "omitted": "#fff7ed",
}

# 目标物品的高亮。它不是「排序」的一种，而是任何节点都可能承担的角色，
# 所以不进 `FILL`：一个 `item:` 节点既可能是目标，也可能只是中间原料，
# 按排序上色无法区分两者。
#
# 配色要求：与所有 `FILL` 都不同色相（其余是蓝/绿/黄/紫/粉/青的浅色），
# 且深色文字在上面对比度足够。琥珀 `#fde68a` + 深棕边框是唯一不冲突的一组。
TARGET_FILL = "#fde68a"
TARGET_BORDER = "#b45309"

# 边色与中文标签。
#
# `implies` 的语义随 head 排序变，必须按 (kind, head 排序) 分开翻译：
# `tag ← item` 是「属于标签」，`station ← item` 是「由该物品搭成」，
# `enchant ← assume` 是「可施加」。只按 kind 翻译会把三种说成同一件事。
KIND_STYLE: dict[tuple[str, str], tuple[str, str]] = {
    ("yield", "item"): ("获得", "#2563eb"),
    ("yield", "block"): ("获得", "#2563eb"),
    ("holds", "table"): ("对应战利品表", "#db2777"),
    ("implies", "tag"): ("属于标签", "#7c3aed"),
    ("implies", "station"): ("由它搭成", "#4f46e5"),
    ("implies", "enchant"): ("可施加", "#a21caf"),
    ("implies", "item"): ("即", "#7c3aed"),
    # 「生成」不是「生成于」：边方向是「来源 → 产物」，`world → block` 读作
    # 「世界生成该方块」。写「生成于」会变成「世界生成于方块」，方向反了。
    ("seeds", "block"): ("生成", "#0d9488"),
    ("seeds", "entity"): ("生成", "#0d9488"),
    ("seeds", "structure"): ("生成", "#0d9488"),
    ("spawns", "entity"): ("生成", "#ca8a04"),
    ("transmutes", "block"): ("变换自", "#ea580c"),
    ("alias", "item"): ("等同", "#64748b"),
    ("variants", "item"): ("变体", "#9333ea"),
    ("unlocks", "item"): ("解锁", "#0891b2"),
}
DEFAULT_EDGE_COLOR = "#94a3b8"
# 条件边（设备 / 工具 / 附魔）的固定颜色：不给东西，只限条件
CONDITION_COLOR = "#b45309"
# 同构簇聚合边：一批规则的合并，不是某一条规则
ISOMORPHIC_COLOR = "#6366f1"


def kind_style(kind: str, head: str) -> tuple[str, str]:
    try:
        sort = split_node(head)[0]
    except ValueError:
        sort = ""
    return KIND_STYLE.get((kind, sort), (kind, DEFAULT_EDGE_COLOR))


def short(value: str) -> str:
    """只为人读的短名；完整 id 留在 tooltip。"""
    return value.replace("minecraft:", "")


_TEMPLATE_PREFIX = re.compile(r"^data/[^/]+/structure/")


def short_template(path: str) -> str:
    """`data/minecraft/structure/village/plains/houses/x.snbt` → `village/plains/houses/x.snbt`。

    保留结构目录段——那正是「哪个结构」的信息；只去掉千篇一律的前缀，
    否则一条便签就能把图撑宽一倍。
    """
    return _TEMPLATE_PREFIX.sub("", path)


# ---------------------------------------------------------------- 规则分类


def craft_of(rule: Rule) -> str:
    """配方 → 工艺名（合成 / 熔炼 / 切石 …）。"""
    serializer = ((rule.meta or {}).get("serializer") or "").removeprefix("minecraft:")
    if serializer.startswith("smithing"):
        return "锻造"
    if serializer.startswith("crafting"):
        return "合成"
    return RECIPE_CRAFT.get(serializer, serializer or "合成")


def station_of(rule: Rule) -> str | None:
    """规则 body 里的设备节点（不带 `station:` 前缀）。实测每条至多一个。"""
    found = [b for b in rule.body if b.startswith("station:")]
    if len(found) > 1:
        raise ValueError(f"{rule.id}: body 含多个 station，聚合假设不成立：{found}")
    return found[0].split(":", 1)[1] if found else None


def table_category(table: str) -> tuple[str, str]:
    """战利品表 → (聚合键, 类别名)。

    `minecraft:chests/ancient_city` → (`loot/chests`, `结构战利品`)。

    只按**目录首段**分类，不逐表登记专名。逐表登记过一版（`gameplay` 下想把
    以物易物与钓鱼分开），结果是同一张图上有的表有专名、有的没有，读者分不清
    哪个是原名、哪个是译名。而 `gameplay/` 内部确实混着不同机制——那类区分
    由**代码事实**给出（`piglin_barter` idiom 把付款物抽出来，表因此有了自己的
    上游），不靠在展示层编名字。
    """
    bare = table.split(":", 1)[-1]
    head = bare.split("/", 1)[0]
    return f"loot/{head}", LOOT_SOURCE.get(head, head or "战利品")


def category_of(rule: Rule) -> tuple[str, str]:
    """规则 → (聚合键, 类别名)。

    只用规则自带字段（`family` / `meta`），不读知识表、不猜。
    键决定「哪些规则算同一种来源」，名字用于标签与 tooltip。
    """
    family = rule.family or ""
    meta = rule.meta or {}

    if family == "loot":
        # `minecraft:blocks/lectern` → 首段 `blocks`。命名空间必须先剥掉，
        # 否则每一类都会叫 `minecraft:blocks`。
        return table_category(meta.get("table") or "")

    if family == "trades":
        # 流浪商人与职业村民的前提不同（IR 里也是两个假设节点），分类必须分开，
        # 否则「流浪商人卖的」会被读成「村民卖的」。其余职业合称村民交易：
        # 它们的前提完全一样，按职业拆只会让同一前提重复 14 次。
        if meta.get("profession") == "wandering_trader":
            return "trades/wandering", "流浪商人"
        return "trades", "村民交易"

    if family == "recipes":
        craft = craft_of(rule)
        return f"recipes/{craft}", craft

    if family.startswith("worldgen"):
        # 「生成」不是「世界生成」：合并进边后，`world --[生成]--> block` 才读得通
        return f"worldgen/{meta.get('worldgen_kind')}", "生成"

    if family.startswith("bindings"):
        # `bindings/template_block`、`bindings/spawn` 等子族写在斜杠后
        sub = family.split("/", 1)[-1] if "/" in family else ""
        return f"bindings/{sub}", BINDINGS_NAME.get(sub, "结构内容")

    if family.startswith("bridge/"):
        sub = family.split("/", 1)[-1]
        return f"bridge/{sub}", BRIDGE_NAME.get(sub, sub)

    if family.startswith("code/"):
        sub = family.split("/", 1)[-1]
        # 1.18.x 的交易表硬编码在源码里，走 `code/villager_trades`。
        # 前提分类与数据包形态一致：流浪商人单列（它有自己的假设节点）。
        if sub == "villager_trades" and meta.get("profession") == "wandering_trader":
            return "code/villager_trades/wandering", "流浪商人"
        return f"code/{sub}", CODE_NAME.get(sub, "代码提取")

    return family or "other", family or "其它"


def sub_key(rule: Rule) -> str:
    """组内的二级细分，只用于 tooltip 与「N 种」标注。"""
    family = rule.family or ""
    meta = rule.meta or {}
    if family == "trades":
        profession = meta.get("profession") or "?"
        if profession == "wandering_trader":
            # 流浪商人整组只有这一种「职业」，拿职业当二级细分等于没有细分。
            # 换成具体货物名（`wandering_trader/emerald_oak_log` → `emerald_oak_log`），
            # 才看得出这 10 条是 10 种木头。
            return (meta.get("trade") or "").rsplit("/", 1)[-1] or profession
        # 只到职业，不带到等级：等级会把职业拆成十几个「种」
        return profession
    if family == "loot":
        # `minecraft:chests/ancient_city` → `ancient_city`
        return (meta.get("table") or "").split(":", 1)[-1].split("/", 1)[-1] or "?"
    if family == "recipes":
        return ((meta.get("serializer") or "").removeprefix("minecraft:")) or "?"
    if family.startswith("worldgen"):
        # `source` 形如 `feature/sculk_patch_ancient_city`，比规则 id 短得多
        return meta.get("source") or (meta.get("worldgen_kind") or "?")
    if family.startswith("code/"):
        # 代码侧交易按职业细分，与数据包形态的 `trades` 保持同一读法
        if family.endswith("villager_trades"):
            return meta.get("profession") or "?"
        return family.split("/", 1)[-1]
    return rule.id


def condition_label(value: str) -> str:
    """条件的显示名：`tool:minecraft:iron_pickaxe` → `铁镐`。

    三类条件（设备 / 工具 / 附魔）都是「要什么」，用名词比 id 好读。
    """
    sort, _, ident = value.partition(":")
    bare = ident.split(":", 1)[-1]
    if sort == "station":
        return STATION_NAME.get(bare, short(ident))
    if sort == "tool":
        return TOOL_NAME.get(bare, short(ident))
    if sort == "enchant":
        return ENCHANT_NAME.get(bare, short(ident))
    return short(value)


def is_condition(value: str) -> bool:
    return value.startswith(CONDITION_PREFIXES)


def condition_lines(rule: Rule) -> list[str]:
    """规则的条件，按类别归组为可读行：`工具：铁镐`、`附魔：精准采集`。

    同类条件合并到一行（`工具：剪刀+精准采集`），否则一个菱形会被竖向拉得很长。
    行内顺序固定为设备 → 工具 → 附魔，与「怎么作业」的阅读顺序一致。
    """
    buckets: dict[str, list[str]] = {"station": [], "tool": [], "enchant": []}
    for cond in rule.body:
        if not is_condition(cond):
            continue
        sort = cond.split(":", 1)[0]
        buckets.setdefault(sort, []).append(condition_label(cond))
    titles = {"station": "设备", "tool": "工具", "enchant": "附魔"}
    return [
        f"{titles[sort]}：{'+'.join(names)}"
        for sort, names in buckets.items()
        if names
    ]


def stacked(items: Iterable[str]) -> str:
    """节点标签里的名单：一行一个，用 DOT 的 `\\n` 分隔。

    用 `、` 串成一行时，3 个 20 字符的名字就是 60 字符宽——folder 会被拉成
    一条细横条，字号跟着缩到看不清。换行之后宽度只取决于最长的那个名字，
    而高度本来是免费的：同层节点按最高者对齐，多两行不额外占版面。

    tooltip 里仍用真正的换行（`\\n` 字符），那里没有排版约束。
    """
    return "\\n".join(items)


def rule_label(rule: Rule, *, inline_conditions: bool = True) -> str:
    """菱形上的标签。

    `inline_conditions` 为真时把条件写进标签第二行。这是默认：条件画成独立节点时，
    三条虚线汇进同一个菱形，读者反而分不清哪条是「东西从哪来」、哪条是「要什么」。
    写在菱形里，一个菱形就是一句完整的话：「挖掘方块 / 工具：铁镐 / 附魔：精准采集」。

    `expand_conditions` 时条件另成节点，标签只留类别——否则同一信息会两处重复。
    """
    name = category_of(rule)[1]
    if not inline_conditions:
        return name
    lines = [name, *condition_lines(rule)]
    return "\\n".join(lines)


def edge_label(rule: Rule, *, inline_conditions: bool = True) -> str:
    """单前件规则合并进边时的边文字。

    比只有类别多一层信息：前置里的附加条件要写清楚，否则合并后读者会以为
    「挖 emerald_ore 就一定掉绿宝石」。
    """
    parts = [category_of(rule)[1]]
    if inline_conditions:
        parts.extend(condition_lines(rule))
    return " · ".join(parts)


def condition_label_text(fixed: tuple[str, ...]) -> str:
    """把固定前置里能读的挑出来，拼成边标签的尾巴。"""
    parts = [condition_label(b) for b in fixed if is_condition(b)]
    return " · ".join(parts)


def root_source_label(
    source: str, edge_label: str = "", templates: tuple[str, ...] = ()
) -> str:
    """全局起点的显示串，用于吸进产物节点的标签。

    三种形态，都由数据决定，不猜：

    | source | edge_label | templates | 结果 |
    |---|---|---|---|
    | `world:overworld` | `生成` | — | `主世界生成` |
    | `world:overworld` | `结构放置` | `village/…` | `结构放置·village` |
    | `assume:structure_content` | `结构生成` | — | `结构生成` |

    「生成」与 world 合并成一句（「主世界生成」比「生成·主世界」像人话）；
    其余保留边标签作主语——`结构放置` 已经说清了动作，再加「主世界」只是噪音。

    结构名**不汉化**（`结构放置·village` 而不是「村庄」）：结构清单随版本增减，
    译名表必然不全，而不全就会变成中英混排。判据见本文件顶部的汉化边界表。
    """
    sort, _, ident = source.partition(":")
    bare = ident.split(":", 1)[-1]
    if sort == "world":
        name = WORLD_NAME.get(bare, bare)
    else:
        name = ASSUME_NAME.get(bare, bare)

    if sort == "world" and edge_label == "生成":
        head = f"{name}生成"
    elif edge_label:
        head = edge_label
    else:
        head = name

    # 只有「结构放置」这类才带结构名：世界生成不是一个具体结构给的，
    # 硬拼上 `data`（模板路径的首段）只是噪音。
    structure = ""
    if head != f"{name}生成":
        for path in templates:
            head_segment = path.split("/", 1)[0]
            if head_segment:
                structure = head_segment
                break
    return f"{head}·{structure}" if structure else head


def source_name(node: str, category: str | None = None) -> str:
    """一个来源节点的可读名，用于桶节点的标签。

    规则节点优先用它的类别名（`category_of` 的返回值）：同一个 family 下可能
    并存不同类别（`trades` 里流浪商人与职业村民），只看 `rule::` 首段会把它们
    说成同一件事。
    """
    if category:
        return category
    if node.startswith("templates::"):
        return "模板"
    if node.startswith("rule::"):
        head = node[6:].split(":", 1)[0]
        return RULE_SOURCE_NAME.get(head, head or "规则")
    try:
        sort = split_node(node)[0]
    except ValueError:
        return node
    return SOURCE_SORT_NAME.get(sort, sort)
