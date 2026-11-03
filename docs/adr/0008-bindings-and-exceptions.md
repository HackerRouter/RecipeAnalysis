# ADR 0008：绑定族与不可获取例外表

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/oa/ir/families/bindings.py`、
  `knowledge/maps/exceptions/unobtainable.json`

## 背景

补完变换、交易、工具之后，不可达项呈现两种形态，都不是「缺一条规则」，而是**缺一整类
事实**：

| 形态 | 例子 | 缺什么 |
|---|---|---|
| 只出现在结构里的方块 | `oxidized_copper_golem_statue` | `block` 节点只从世界生成 feature 与 `bridge:place` 得来，两条都不沾 |
| 只在结构里生成的生物 | `elder_guardian`、`evoker` | `entity` 节点只从 feature 与 spawn egg 得来 |

于是 `item ← table ← block` 整段悬空。

## 一、模板方块 → `block`

`template` 事实的 `blocks` 字段是这些方块的唯一来源。

```
block:minecraft:oxidized_copper_golem_statue  ←seeds←  world:minecraft:overworld
```

**为什么接到 `world` 而不是某个 `structure`**：把模板精确归到结构，需要一张
类名/目录名 → 结构 ID 的对照表，而两者并不一一对应（`abandoned_camp/` 对应 18 个
`abandoned_camp_*`）。这张表只能人工维护，与「不写清单」冲突。

跨这一步的依据是存在性语义：模板只可能作为结构的一部分生成，而结构已由 `worldgen`
事实确认可生成，所以「模板里有这个方块」足以断定「世界里生成得出它」。

**不会把不可获取的方块混进来**：`block → item` 只经战利品表，而战利品表正是「挖掉它
掉什么」的事实来源。原版不给 `bedrock`、`barrier`、`command_block` 发战利品表——虽然
`bedrock` 确实在模板里，也不会产出物品规则。这条性质由事实保证，代码里不需要特判。

head 已存在不等于已覆盖：同一 head 多规则是 **OR**，多发一条是新增一条获取路径，
不是重复。跳过「已有来源规则的 head」会丢掉一条本来就唯一可行的腿，表现为可达率偏低
而没有任何报错。所以总是发，`template_blocks_already_seeded` 只作统计。

## 二、结构刷怪 → `entity`

结构 JSON 的 `spawn_overrides` 是「结构生成什么实体」的唯一数据包来源。

```
entity:minecraft:guardian     ←spawns←  structure:minecraft:monument
structure:minecraft:monument  ←seeds←   world:minecraft:overworld
```

`spawns` 与 `seeds` 分开：`references` 记「放置了什么方块」，`spawns` 记「会冒出什么
实体」，两者在适配器里就是两个字段，不混进同一个列表。

结构 id 有两种来源形态，`_structure_node()` 都要认：数据包是
`data/<ns>/worldgen/structure/<名>`（能读命名空间），运行期导出是
`configured_structure_feature/<名>`（退回 `minecraft:`，运行期只含原版条目）。

## 三、结构生成器代码里的实体

`elder_guardian` 与 `evoker` 不在 `spawn_overrides` 里——它们在结构拼装器的生成代码里
直接 `create`。新增 idiom `structure_entities`，判据是**路径 + 类名后缀**而不是实体名：

1. 路径含 `/structure/`，类名以 `Pieces` 结尾
2. 实参含 `EntitySpawnReason.STRUCTURE`（26.3），或 `create` 只有一个实参（1.18.2）

两版各命中 `shulker`、`elder_guardian`、`drowned`、`evoker`、`vindicator`
（26.3 另有 `allay`，该版本才加入）。全是真正的结构生物，没有误收。

前提用假设节点 `assume:structure_content`（「结构里装进去的东西可取得」）。不绑结构名，
理由同第一节。

## 四、不可获取例外表

补完上面三条，剩下两类情形混在一起报 `no_rule`：确定不可获取的（`bedrock`、`barrier`、
命令方块……）与有机制但尚未提取的（`nether_star`、`lava_bucket`……）。报告无法回答
「这些为什么都没有路径」。

`knowledge/maps/exceptions/unobtainable.json` 给出的归因是 `unobtainable`，并带类别与依据：

| 类别 | 判据 | 例子 |
|---|---|---|
| 技术方块 / 命令专用 | 全库无创造页收录 | `command_block`、`light`、`knowledge_book` |
| 不可破坏 | 任何工具（含精准采集）都挖不下来 | `bedrock`、`reinforced_deepslate` |
| 生存无途径 | 地形变体、宿主方块，挖回掉的是别的 | `farmland`、`infested_stone` |

该表只收录确定不可获取的条目。凡在数据包或代码里有获取机制的，一律不入表，即使该项
机制尚未提取——该类情形留在 `no_rule` 作为待补项。只有当此条成立时，`no_rule` 才只有一个含义。

`gaps.jsonl` 不含 `unobtainable`：它不是缺口，是已解释的结论。

## 后果

- `bindings` 成为独立族（`families/bindings.py`）
- 新增 idiom `structure_entities`、新增锚点 `structure_entity_reason` 与
  `structure_piece_create`
- `no_rule` 从笼统桶变成「已知待补」这一个含义
