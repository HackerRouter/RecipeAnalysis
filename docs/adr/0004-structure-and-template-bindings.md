# ADR 0004：结构内容与模板绑定

有些方块与实体只出现在结构里：铜傀儡像、雕刻南瓜、损坏的铁砧、远古守卫者、唤魔者、村民。它们的共同点是**不属于世界生成 feature，也不属于配方**，因此 `block` / `entity` 节点没有来源，`item ← table ← block` 整段悬空。

三条数据来源覆盖它们：模板 NBT、结构 JSON 的 `spawn_overrides`、结构拼装器的生成代码。

## 一、模板里的方块 → `block`

```
block:minecraft:oxidized_copper_golem_statue  ←seeds←  world:minecraft:overworld
```

**为什么接 `world` 而不是某个 `structure`**：把模板精确归到结构需要一张类名/目录名到结构 ID 的对照表，而两者并不一一对应（`abandoned_camp/` 对应 18 个 `abandoned_camp_*`）。这张表只能人工维护，与「不写清单」冲突。

跨这一步的依据是存在性语义：模板只可能作为结构的一部分生成，结构已由 `worldgen` 事实确认可生成，所以「模板里有这个方块」足以断定「世界里生成得出它」。

**不会把不可获取的方块混进来**：`block → item` 只经战利品表，而战利品表正是「挖掉它掉什么」的事实来源。原版不给 `bedrock`、`barrier`、`command_block` 发战利品表——虽然 `bedrock` 确实在模板里，也不会产出物品规则。这条性质由事实保证，不需要特判。

**head 已存在不等于已覆盖**：同一 head 多规则是 OR，多发一条是新增一条获取路径。跳过「已有来源的 head」会丢掉一条本来唯一可行的腿，表现为可达率偏低而无任何报错。所以总是发，`template_blocks_already_seeded` 只作统计。

## 二、模板里的实体 → `entity`

模板 NBT 的 `entities` 字段是某些实体的唯一数据包踪迹：

```json
{"template": "village/plains/houses/plains_library_1.snbt",
 "entities": [{"id": "minecraft:villager", "has_equipment": true, "blockPos": [2,1,1]}]}
```

村民**不由任何生物群系的刷怪表生成**，也不由配方产出。不读这个字段，`entity:villager` 零规则、状态 FALSE，所有以村民为前提的机制一起断链。

与模板方块同一处理：body 是 `world:overworld`，不绑定到具体结构（模板事实只给模板路径，`structure:` 与目录名之间没有可复算的映射）。

`entities` 里也会出现非实体 id（`minecraft:cushion` 是方块实体），注册表校验不过的进 `unknown_entities`，由编译期 note 指出。

| 做法 | 错在哪 |
|---|---|
| 把村民挂到 `assume:*` | 那是「交易可发生」的前提，不是「村民存在」的事实；两者混同会让 `ra why` 分不清「假定能交易」与「结构里有村民」 |
| 用刷怪表近似 | 村民不在刷怪表里，按「哪些群系生成村民」去补会得到空集，然后被读成「村民不可获得」 |
| 只补 `entity:villager` 这一个特例 | 同一字段里还有猫、马、铁傀儡、猪灵；单点修补会让下次遇到同类时再犯一遍 |
| 推一个结构 ID 当 body | 硬拼会造出假节点，比缺一条边更糟（假节点会被当成已覆盖） |

## 三、结构 JSON 的刷怪 → `entity`

```
entity:minecraft:guardian     ←spawns←  structure:minecraft:monument
structure:minecraft:monument  ←seeds←   world:minecraft:overworld
```

`spawns` 与 `references` 分开：后者记「放置了什么方块」，前者记「会冒出什么实体」，在适配器里就是两个字段。

结构 id 有两种形态，`_structure_node()` 都要认：

| 来源 | id 形态 |
|---|---|
| 数据包 | `data/<ns>/worldgen/structure/<名>`，能读命名空间 |
| 运行期导出 | `configured_structure_feature/<名>`，退回 `minecraft:`（运行期只含原版条目） |

**空 `spawn_overrides` 不等同于缺陷**：「结构内不额外刷怪」与「结构不存在」是两个结论。试炼密室的怪物全部来自刷怪笼，配置在 `data/<ns>/trial_spawner/**`，是另一个事实种类。

## 四、结构拼装器代码里的实体 → `entity`

`elder_guardian` 与 `evoker` 不在 `spawn_overrides` 里，它们在结构拼装器的生成代码里直接 `create`。idiom `structure_entities` 的判据是**路径 + 类名后缀**，不是实体名：

1. 路径含 `/structure/`，类名以 `Pieces` 结尾
2. 实参含 `EntitySpawnReason.STRUCTURE`（新版本），或 `create` 只有一个实参（1.18.2）

前提用 `assume:structure_content`（「结构里装进去的东西可取得」），不绑结构名——类名与结构 ID 不一一对应（`OceanMonumentPieces` 对应 `monument`）。

## 五、例外表要早于其它归因

`petrified_oak_slab` 有战利品表也有放置桥，两者互指成环，`cycle_no_entry` 暗示「只差一步即可获取」，而实际结论是「命令专用」。所以 `attribute()` 把例外表检查提到其余全部归因之前。

物品往往**有**规则，只是那些规则不成立；先看规则会得到误导性的分类。因此 `unobtainable` 可出现在 `no_rule` 之外的归因里。`suspicious_sand` 是最典型的例子：方块在世界生成中可达，但战利品表为空，挖除不掉本体——方块可生成不等同于物品可获取。

成片规律用 `_patterns` 段表达（`{match: "*_spawn_egg"}`、`{items: [...]}`），避免把 88 个刷怪蛋逐条写进例外表。展开只在有全集时进行，`attribute()` 的查表逻辑不变。

## 后果

- `bindings` 族产出 `template_block` / `template_entity` / `template_item` / `spawn` 四类规则
- 结构生成器实体由 `code_link` 的 `spawns` 进 IR，family 为 `code/structure_entities`
- 模板事实里出现、注册表里没有的 id 一律留痕，不静默跳过
