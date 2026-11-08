# ADR 0003：世界生成的引用形态与代码侧补全

世界生成事实的 `references` 是「世界里生成了什么方块、实体、结构」的主要来源。它有两种失效方式：判据按单个键写时整片漏掉，而漏掉不报错；以及方块名根本不在 JSON 里。

## 一、判据按整块键集合，不按单个键

按「键名在白名单里」或「必须同时出现某两键」判定，会漏掉省略可选键的合法写法。症状是事实照产，只是那些方块不在 `references` 里，最终表现为「物品不可达，归因是自指成环」。

### 状态对象可以没有属性表

```json
"root_state_provider": { "id": "minecraft:rooted_dirt" }
```

默认状态没有可写属性时 `properties` 整块省略。旧判据要求两键同时出现，于是这类方块全丢。1.18.2 的 `{"Name": ..., "Properties": {...}}` 同理。

判据是**键集合**：除状态专有键外没有别的键，就是状态对象。单看 `id` 太宽（模板池、群系源也用它）。

### 加权提供者的表项用 `data`

```json
"entries": [{ "data": "minecraft:azalea_leaves", "weight": 3 }]
```

`data` 太常见，只在**同层有 `weight`** 时当成方块——那是加权表项的形状，不是全局约定。

### 裸 id 列表

```json
"inner_placements": ["minecraft:small_amethyst_bud", "minecraft:amethyst_cluster"]
```

按逐键列举（`inner_placements`、`blocks`），不用后缀通配：枚举会随版本漏，通配会误收约束类键。

### 值是方块标签

```json
"to_place": { "type": "minecraft:random_block", "blocks": "#minecraft:corals" }
```

适配器只记 `{"slot": "tag", "id": "minecraft:corals"}`，展开放 IR。这一步是语义不是语法。

### 约束子树不是产物

`replaceable_blocks`、`cannot_replace`、`invalid_blocks` 一类键的值是**谓词**，说的是「什么允许被覆盖」。它们与放置提供者同形：

```json
"replaceable_blocks": {
  "type": "minecraft:matching_blocks",
  "blocks": ["minecraft:chorus_plant", "minecraft:crimson_fungus"]
}
```

照键名 `blocks` 取值会把整张白名单当产物：巨大菌类（`crimson_fungus`）的可覆盖目标里有 `chorus_plant`，世界生成于是多出一条「`chorus_plant` 来自下界菌类」。约束键必须在递归时整棵跳过，不产 `references`。

判据是**显式列举**（`adapters/worldgen.py` 的 `CONSTRAINT_KEYS`），不用后缀通配：同一层里 `replace_with_blackstone` 是布尔开关、`invalid_blocks_threshold` 是数值，按 `replace`/`invalid` 通配会把它们误当约束键。

## 二、排序按注册表锚定，不按字段名

`slot` 只有 `block` / `entity` / `tag` / `feature` / `structure` / `template` 几种，其中 **`entity` 是兜底**——无法归类的引用都落在这里，它不代表「实体」。

实测 `noise_settings` 的默认方块（`minecraft:stone`）被标成 `slot=entity`。只信 slot，地表方块就全部不可达，整条掉落链断。

判据是**引用 ID 命中哪个注册表就按哪个排序**。与阶段一 probe 的原则一致：用注册表当锚点，不靠字段名猜。

## 三、标签放置的展开

```
tag:block/minecraft:corals     ←seeds←    world:minecraft:overworld
block:minecraft:brain_coral    ←implies←  tag:block/minecraft:corals
```

存在性语义使每个成员都判为真：随机选择意味着每个成员被选中的概率非零，世界无限则必然出现足够多次。这与「定义了就是有」是同一条语义。

标签展开只适用于放置类标签。约束类标签（`cannot_replace`、`invalid_blocks`、`geode_invalid_blocks`）说的是「什么可以被替换」，照它们展开会把基岩、空气判成可获取。适配器用 `TAG_PLACEMENT_KEYS` 逐键列举，不用后缀通配。

标签不存在或展开为空时返回空，调用方计入 `unresolved_refs['tag']`，不产一条永不成立的规则。

## 四、方块名不在 JSON 里的特征

有一类特征只在 JSON 里写参数，方块名落在实现类里：

```json
// worldgen/feature/sculk_patch_deep_dark.json —— 没有任何方块字段
{"type": "minecraft:sculk_patch", "amount_per_charge": 32, "charge_count": 10, ...}
```

```java
// SculkPatchFeature#place —— 只创建扩散器
SculkSpreader spreader = SculkSpreader.createWorldGenSpreader();
// SculkVeinBlock#attemptPlaceSculk —— 方块在这里
BlockState defaultSculk = Blocks.SCULK.defaultBlockState();
```

同目录的 `feature/sculk_vein.json` 写了 `"block": "minecraft:sculk_vein"`，所以幽匿脉络能提取到；`sculk` 提取不到，只剩「方块 ← 物品 ← 方块掉落表」这一圈循环。

由知识表 `knowledge/maps/mechanism/worldgen_code_blocks.json` 补：键是特征类型，值是它铺出的方块，`worldgen_code_rules` 产 `block:X ←seeds← world`。

### 门控是特征事实的引用，不是顶层 `type`

| 门控 | 结果 |
|---|---|
| 该版本的 `worldgen` 事实的 `references` 里出现该类型 id | 生效 |
| 方块在该版本 block 注册表里 | 生效；否则记 `unknown_block` |

不能按特征 JSON 的顶层 `type` 匹配：顶层往往只是容器（`sequence`），`sculk_patch` 是 `features` 数组里的元素。实测按 `type` 匹配得到 0 条。

第一条门控承担跨版本职责：表里写 `minecraft:sculk_patch` 不会让没有深暗之域的版本产出规则，不需要在表里写版本条件。

## 换一种做法会错在哪

| 做法 | 错在哪 |
|---|---|
| 在特征类里找 `Blocks.X` | `SculkPatchFeature` 类体里唯一的是 `Blocks.WATER`（地形判据），会把它当成产出 |
| 写 idiom 跟踪扩散链 | 链跨类（feature → spreader → behaviour → 方块类），要写一套专用调用链分析，只服务一个特征 |
| 让行为族兼任 | 「催发体转化附近死亡生物」与世界生成是两条机制，合并后证据指向错误的主体 |
| 用 `actor: world:` 写进行为表 | 规则退化为 `block:sculk ← world`，没有事实做依据；同一张表在其他版本会因此凭空得到节点 |
| 直接补进 `worldgen` 事实的 `references` | 适配器只做语法还原；把代码里的知识写进数据包事实，割断 `prov` 与真实来源的对应 |

## 后果

- 代码侧规则带 `meta.feature_type` / `features` / `basis` / `evidence`，`prov` 指向特征事实的 JSON，代码位置在 `evidence` 里
- 方块引用有四种写法，枚举验证用 `tools/probes/probe-worldgen-refs.py`
