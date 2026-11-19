"""黄金样本：已知答案，跨版本。

黄金样本约 30 个，覆盖各链接种类与各类归因。
这些不是「跑出来什么就记什么」——每条都经过语义核对，钉的是**机制**
（走哪一类来源、缺什么、为什么拿不到），不是某条规则的 id 或某个实现的细节。

## 为什么钉族而不是钉 rule id

`rule.id` 里带文件路径与序号，加一条规则就会变。钉它等于每改一次知识表都要
改测试，而那些改动本身可能就是对的。所以断言用三个维度：

| 断言 | 含义 | 稳定性 |
|---|---|---|
| `status` | 可达 / 不可达 | 高 |
| `reason` | 不可达时归因为哪一类 | 高 |
| `family` | 证明链里出现哪些来源族 | 中（族是固定的分层） |
| `node` | 证明链里出现哪些节点 | 中（节点名是契约） |

`family` 用「必须出现」而不是「等于」：同一物品多几条路径是好事，不该判失败。

## 为什么区分版本

同一物品在两版的机制可能完全不同（剪毛：26.3 走数据包 `shearing/` 表，
1.18.2 走 `Sheep.java` 的静态映射）。反过来，某些物品在某个版本不存在
（`breeze_rod` 是 1.21 引入的）。所以样本按 `(版本, 节点)` 索引。

## 覆盖检查

`test_golden.py` 有一条断言核对本表覆盖了 `REQUIRED` 列举的每一类：
双路径、机制搬家、别名、代码承载、工具门槛、变体、未知依赖、无来源、循环、模板承载。

另有一条核对「每份输入包都有样本」：版本清单取自 `support.known_labels()`
（扫描 `inputs/*/`），所以加版本时漏补样本会直接失败，而不是静默少测一版。

## 待补：三个断言字段目前基本空转

`absent_family` / `missing_any` / `cycle_any` 是反向与归因断言，但样本很少填
（详见 `Sample` 里的注释）。它们对应的三条测试因此基本不验证任何东西。
补样本前不要以为「反向断言已被覆盖」。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    """一个黄金样本。

    `family` / `node` 是**必须出现**，不是精确集合。`absent_family` 用于
    反向断言（「不该靠某族拿到」），只在确实需要防止退化时写。
    """

    node: str
    status: str
    covers: str
    note: str = ""
    reason: str = ""
    # 证明树里必须出现的来源族（前缀匹配，如 `code/mob_buckets`）
    family: tuple[str, ...] = ()
    # 证明树里必须出现的节点
    node_contains: tuple[str, ...] = ()
    # 证明树里不得出现的来源族
    #
    # **风险（待补样本）**：目前没有任何样本填写 `absent_family`，而
    # `_GoldenBase.test_families_absent` 是靠它驱动的——每条样本都被
    # `if not sample.absent_family: continue` 跳过，所以那条测试恒真。
    # `missing_any` / `cycle_any` 同样：只有 1.18.2 各有一条样本命中，
    # 26.3 的对应测试恒真。补样本后删掉本注。
    absent_family: tuple[str, ...] = ()
    # 不可达时：缺项里必须出现其中之一（同上，26.3 目前无样本使用）
    missing_any: tuple[str, ...] = ()
    # 不可达时：环里必须出现其中之一（同上，26.3 目前无样本使用）
    cycle_any: tuple[str, ...] = ()
    # 规则条数下限（钉「多路径」这件事本身）
    min_alternatives: int = 0


# --- 26.3（内容提交 c1fd2a862）---------------------------------------------
SAMPLES_263: tuple[Sample, ...] = (
    Sample(
        node="item:minecraft:iron_ingot",
        status="true",
        covers="双路径",
        note="矿石熔炼与箱子战利品是两条独立路径",
        family=("loot",),
        min_alternatives=5,
    ),
    Sample(
        node="item:minecraft:diamond",
        status="true",
        covers="双路径",
        note="矿石掉落与结构战利品",
        family=("loot",),
        min_alternatives=5,
    ),
    Sample(
        node="item:minecraft:cobblestone",
        status="true",
        covers="世界生成",
        note="世界生成 → 方块 → 表 → 物品",
        family=("worldgen",),
        node_contains=("world:minecraft:overworld",),
    ),
    Sample(
        node="item:minecraft:white_wool",
        status="true",
        covers="变体",
        note="26.3 的剪毛表在数据包 shearing/ 下，由目录约定挂到实体并带剪刀前置；1.18.2 在 Sheep.java",
        family=("loot", "bridge/table"),
        node_contains=("entity:minecraft:sheep", "tool:minecraft:shears"),
    ),
    Sample(
        node="item:minecraft:dragon_head",
        status="true",
        covers="别名",
        note="龙首复用僵尸/骷髅头的战利品表（loot_alias）",
        family=("loot",),
    ),
    Sample(
        node="item:minecraft:elytra",
        status="true",
        covers="代码承载",
        note="数据包完全没有；只有 EndCityPieces 的 marker 分支里有",
        family=("code/structure_gadgets",),
    ),
    Sample(
        node="item:minecraft:obsidian",
        status="true",
        covers="工具门槛",
        note="需要钻石镐才掉；工具前置由 bridge/tool 给",
        family=("loot",),
    ),
    Sample(
        node="item:minecraft:glow_lichen",
        status="true",
        covers="工具门槛",
        note="需要剪刀；剪刀是不可再生工具类的单件桥接",
        family=("bridge/tool",),
        node_contains=("tool:minecraft:shears",),
    ),
    Sample(
        node="item:minecraft:cod_bucket",
        status="true",
        covers="多路径",
        note="代码捞桶与渔夫交易两条",
        family=("code/mob_buckets", "trades"),
        min_alternatives=2,
    ),
    Sample(
        node="item:minecraft:lava_bucket",
        status="true",
        covers="流体桶",
        note="BucketItem 构造器；空桶是消耗品，被装进去的熔岩是 `via` 方块前置",
        family=("code/fluid_buckets",),
        node_contains=("item:minecraft:bucket", "block:minecraft:lava"),
    ),
    Sample(
        node="item:minecraft:nether_star",
        status="true",
        covers="召唤与死亡掉落",
        note="凋灵的 entities/wither 表是空的；只有 WitherBoss 里 spawnAtLocation 那一句",
        family=("code/death_drops",),
        node_contains=("entity:minecraft:wither",),
    ),
    Sample(
        node="item:minecraft:beacon",
        status="true",
        covers="配方链",
        note="下界之星是它的硬前置，所以这条样本同时验证召唤链",
        family=("recipe",),
        node_contains=("item:minecraft:nether_star",),
    ),
    Sample(
        node="item:minecraft:breeze_rod",
        status="true",
        covers="刷怪笼",
        note="breeze 只在 trial_spawner 注册表里，世界生成没有",
        family=("bindings/spawner",),
        node_contains=("entity:minecraft:breeze",),
    ),
    Sample(
        node="item:minecraft:flow_pottery_sherd",
        status="true",
        covers="模板承载",
        note="不在任何战利品表；陶罐的 nbt.sherds 是唯一踪迹",
        family=("bindings/template_item",),
        node_contains=("block:minecraft:decorated_pot",),
    ),
    Sample(
        node="item:minecraft:red_concrete",
        status="true",
        covers="约定变换",
        note="粉末遇水固化，靠 _powder 后缀配对",
        family=("bridge/convention",),
    ),
    Sample(
        node="item:minecraft:oxidized_copper",
        status="true",
        covers="逆向变换",
        note="自然氧化是刮削的逆；没有事实能直接给这个方向",
        family=("code/transform",),
    ),
    Sample(
        node="item:minecraft:furnace",
        status="true",
        covers="自环但有入口",
        note="有 block⇄item 回路，但配方是独立入口；归因不得误报 cycle",
        family=("recipe",),
    ),
    Sample(
        node="item:minecraft:enchanted_book",
        status="true",
        covers="交易",
        note="图书馆员交易是主要来源",
        family=("trades",),
    ),
    Sample(
        node="item:minecraft:bedrock",
        status="false",
        covers="无来源",
        reason="unobtainable",
        note="不可破坏；例外表登记",
    ),
    Sample(
        node="item:minecraft:barrier",
        status="false",
        covers="无来源",
        reason="unobtainable",
        note="命令专用；例外表登记",
    ),
    Sample(
        node="item:minecraft:petrified_oak_slab",
        status="false",
        covers="无来源",
        reason="unobtainable",
        note="有战利品表也有放置桥，两者互指；例外表优先于环归因",
    ),
    Sample(
        node="item:minecraft:suspicious_sand",
        status="false",
        covers="方块可生成但物品不可得",
        reason="unobtainable",
        note="方块在世界生成里，但战利品表为空，挖掉不掉本体",
    ),
    Sample(
        node="item:minecraft:tadpole_bucket",
        status="true",
        covers="实体行为",
        note="蝌蚪由青蛙卵孵化、卵由青蛙产下；三环行为链把「末路」变成可达",
        family=("code/mob_buckets", "bridge/entity_behaviour"),
        node_contains=("entity:minecraft:tadpole", "block:minecraft:frogspawn"),
    ),
    Sample(
        node="item:minecraft:bee_nest",
        status="true",
        covers="实体行为",
        note="树生成时挂蜂巢方块；方形可达后仍需精准采集才掉自己",
        family=("bridge/entity_behaviour",),
    ),
    Sample(
        node="item:minecraft:frogspawn",
        status="false",
        covers="方块可生成但物品不可得",
        reason="unobtainable",
        note="青蛙能产出青蛙卵方块，但卵只能在水下孵化，挖碎不掉物品；战利品表是空表",
    ),
    Sample(
        node="item:minecraft:filled_map",
        status="true",
        covers="玩家行为",
        note="空地图被玩家探索填充：物品换形，不是合成；制图师卖的是空地图",
        family=("bridge/item_conversion",),
    ),
    Sample(
        node="item:minecraft:leather",
        status="true",
        covers="实体来源",
        note="行商羊驼随流浪商人生成、骡由马与驴繁殖；两者的皮革战利品表因此可及",
        family=("bridge/entity_source",),
        node_contains=("entity:minecraft:mule", "entity:minecraft:trader_llama"),
    ),
    Sample(
        node="item:minecraft:sculk",
        status="true",
        covers="实体行为",
        note="二腿都在代码里：催发体转化死亡生物，sculk_patch 特征的方块名未写进 feature JSON",
        family=("bridge/entity_behaviour", "bridge/worldgen_code"),
        node_contains=("block:minecraft:sculk", "block:minecraft:sculk_catalyst"),
    ),
    Sample(
        node="item:minecraft:milk_bucket",
        status="true",
        covers="交互来源",
        note="对牛/蘑菇牛/山羊用铁桶挤奶；该机制没有配方也没有战利品表",
        family=("bridge/entity_behaviour",),
        node_contains=("entity:minecraft:cow", "item:minecraft:bucket"),
    ),
)


# --- 1.18.2（内容提交 31fe747c6）--------------------------------------------
SAMPLES_1182: tuple[Sample, ...] = (
    Sample(
        node="item:minecraft:white_wool",
        status="true",
        covers="机制搬家",
        note="剪毛走 Sheep.java 的静态映射，不是数据包表",
        family=("code/sheep_shear",),
        node_contains=("entity:minecraft:sheep", "tool:minecraft:shears"),
    ),
    Sample(
        node="item:minecraft:nether_star",
        status="true",
        covers="召唤与死亡掉落",
        note="该版 spawnAtLocation 只有一个实参",
        family=("code/death_drops",),
        node_contains=("entity:minecraft:wither",),
    ),
    Sample(
        node="item:minecraft:cod_bucket",
        status="true",
        covers="多路径",
        note="该版数据包侧没有交易表，渔夫交易在代码里",
        family=("code/mob_buckets",),
        min_alternatives=2,
    ),
    Sample(
        node="item:minecraft:elytra",
        status="true",
        covers="代码承载",
        note="两版同在结构拼装器的 marker 分支",
        family=("code/structure_gadgets",),
    ),
    Sample(
        node="item:minecraft:cobblestone",
        status="true",
        covers="世界生成",
        note="该版世界生成来自运行期导出而非数据包",
        family=("worldgen",),
    ),
    Sample(
        node="item:minecraft:dragon_breath",
        status="true",
        covers="实体行为",
        note="两版都由 BottleItem 接龙息",
        family=("bridge/entity_behaviour",),
    ),
    Sample(
        node="item:minecraft:brain_coral",
        status="false",
        covers="循环无入口",
        reason="cycle_no_entry",
        note="该版世界生成取自运行期导出，珊瑚标签引用没进事实，只剩死亡变体循环",
        cycle_any=("block:minecraft:brain_coral",),
    ),
    Sample(
        node="item:minecraft:cake",
        status="true",
        covers="代码承载",
        note="村民交易；前提是 assume:villager_trade，不依赖 entity:villager 可达"
        "（后者在两版都零规则，曾导致该版整批交易恒假）",
        family=("code/villager_trades",),
    ),
    Sample(
        node="item:minecraft:zombie_head",
        status="false",
        covers="未知依赖",
        reason="blocked",
        note="有方块战利品表，但方块本身不可得：僵尸头不靠挖掘，只由闪电苦力怕炸出",
        missing_any=("table:minecraft:blocks/zombie_head",),
    ),
    Sample(
        node="item:minecraft:bedrock",
        status="false",
        covers="无来源",
        reason="unobtainable",
    ),
    Sample(
        node="item:minecraft:leather",
        status="true",
        covers="实体来源",
        note="该版 WanderingTraderSpawner 与马/驴繁殖的写法与 26.3 同构",
        family=("bridge/entity_source",),
        node_contains=("entity:minecraft:mule", "entity:minecraft:trader_llama"),
    ),
    Sample(
        node="item:minecraft:honeycomb",
        status="true",
        covers="交互来源",
        note="该版没有 harvest/ 战利品表：蜂巢产蜜脾写在 BeehiveBlock#use 里，剪刀是硬前置",
        family=("bridge/entity_behaviour",),
        node_contains=("block:minecraft:beehive", "tool:minecraft:shears"),
    ),
)

ALL_SAMPLES: dict[str, tuple[Sample, ...]] = {
    "26.3": SAMPLES_263,
    "1.18.2": SAMPLES_1182,
}
