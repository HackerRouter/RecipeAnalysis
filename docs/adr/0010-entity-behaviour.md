# ADR 0010：实体行为族与实体来源的种类划分

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/oa/ir/bridges/entities.py`、
  `knowledge/maps/mechanism/entity_behaviour.json`

## 背景

补完绑定与例外表之后，剩下的不可达项里有 10 项是同一种形态：**产出物的代码形状各不
相同，但语义都是「某个 actor 做了某件事，于是产出这个物品」**。

| 物品 | 谁 | 怎么产出 |
|---|---|---|
| `dragon_egg` | 末影龙 | 死亡时 `setBlockAndUpdate` |
| `dragon_breath` | 末影龙 + 玻璃瓶 | `BottleItem` 的 `turnBottleIntoItem` |
| `turtle_egg` | 海龟 | blockstate 属性自增 |
| `tadpole` | 青蛙卵 | tick 里的随机孵化 |
| `frogspawn` | 青蛙 | brain 的 `LAY_SPAWN` 行为步骤 |
| `player_head` | 玩家 | 被闪电劈 |
| `bee_nest` | 树生成 | 世界生成时挂上方块 |
| `chipped_anvil` | 铁砧 | 使用中损耗换形态 |
| `filled_map` / `written_book` | 玩家 | 容器合成 |

## 一、为什么不写成 idiom

`idioms/` 下的适配器都是「在反编译源码里认出一个固定代码形状」。这 10 项没有共同形状，要覆盖
就得写 10 个适配器，每个只命中 1 处，而且每次 MC 改内部结构都会误报。

**更关键的是判据口径**：idiom 的产出是「反编译源码取证」——它证明的是「阅读反编译源码看到这条路径」。
这 10 项的语义可以直接从游戏行为断言，不需要读懂实现。把它们塞进 idiom，等于把「已知
事实」伪装成「反编译源码证据」，混淆了两类可信度。

## 二、声明式表的形态

`knowledge/maps/mechanism/entity_behaviour.json`，字段：`produces`（产出节点全称，任意
sort）、`actor`（执行者，任意 sort）、`inputs`（可选消耗品）、`basis`（可复算依据）、
`evidence`（取证方式）。

生成的规则是 `bridge:behaviour:{name}:{index}`，`kind="yield"`，body = `[actor, *inputs]`，
meta 携带 `behaviour` / `actor` / `basis` / `evidence`。一条表项可产多个 `produces`，
展开成多条规则，rule id 用 index 区分。

## 三、`assume:` 前缀

`player_head`、`filled_map`、`written_book` 的 actor 是玩家。玩家没有注册表节点，也不是
实体事实里的条目——它是一个约定：**分析假定玩家在场且会操作**。

sort 里原没有 `assume:`。这里新增它，只用于「分析前提」，语义上等价于自由变量。它的
存在让「玩家做了什么」这类事实有地方落，而不必伪造一个 `entity:player`——那会污染实体
注册表统计，也会让「玩家能不能自然生成」这种问题变得无意义。

除 `bridge/entity_behaviour` 外没有族读 `assume:`，求解器把它当种子（恒真）。

## 四、`entity_sources` 的种类划分

补末影龙时发现它有两条不同性质的路：

| kind | 例子 | body |
|---|---|---|
| `summon` | `wither` | `tag:block/...wither_summon_base_blocks` + `item:...wither_skeleton_skull` |
| `dimension` | `ender_dragon` | `assume:end`（末地在场即有） |

末影龙走 `EntitySpawnReason.EVENT`，是 `EndPodiumFeature` 里的一次性放置，任何外部 idiom
都认不出来。把它归为 `dimension` 是诚实的建模：末地维度存在 ⟹ 末影龙存在，这条事实
不需要反编译源码取证。

所以函数名为 `entity_source_rules`，family 为 `bridge/entity_source`，`kind` 字段区分两类。
未知 kind 记 `unknown_kind` problem，不静默。

## 五、与例外表的分界

`frogspawn` 一度想放进行为族：青蛙确实产出青蛙卵方块。但它**不产出物品**——方块只能
在水下孵化，挖碎时战利品表是空的。这条走例外表（`unobtainable`），不走行为族。

判据：**行为族管「如何获取」，例外表管「确定不可获取」**。一个物品若在行为族里有 entry 却仍
不可达，那说明 entry 写错了，不是例外表该管的。行为族覆盖这 10 项后，剩余不可达全部
落到 `unobtainable`，`blocked` 归零——这是两套机制没有重叠的证据。

## 后果

- 新增知识表 `entity_behaviour.json`（10 项）
- 新增族 `bridge/entity_behaviour`，新增 sort 前缀 `assume:`
- `entity_summon_rules` → `entity_source_rules`，family `bridge/summon` →
  `bridge/entity_source`
- 黄金样本新增「实体行为」类
