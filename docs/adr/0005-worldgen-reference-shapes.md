# ADR 0005：世界生成里方块引用的四种写法

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/ra/adapters/worldgen.py`、`src/ra/ir/families/worldgen.py`

## 背景

按「键名在白名单里，或字典同时含 `id` 与 `properties`」判定，会漏掉四种实际写法，而且
**漏得很安静**：事实照样产，只是那些方块不出现在 `references`
里，于是世界生成规则少掉一大片，最终表现为「物品不可达，归因是自指成环」。

**判据要按整块键集合，不按单个键**：只认白名单键或「必须同时出现某两键」，会把
省略了可选键的合法写法整片漏掉，而漏掉不报错。

## 四种写法

### 一、状态对象可以没有属性表

```json
"root_state_provider": { "id": "minecraft:rooted_dirt" }
```

默认状态没有可写属性时 `properties` 整块省略。旧判据要求 `properties` 同时出现，
于是这类方块全丢。1.18.2 的 `{"Name": ..., "Properties": {...}}` 同理。

判据用**键集合**：除状态专有键外没有别的键，就是状态对象。单看 `id` 太宽
（模板池、群系源也用它），键集合能把它们排除在外。

守卫：`test_bare_id_without_properties`、`test_all_four_writings`。

### 二、加权提供者的表项用 `data`

```json
"entries": [{ "data": "minecraft:azalea_leaves", "weight": 3 }]
```

`data` 是太常见的键名，只在**同层有 `weight`** 时当成方块——那是加权表项的形状，
不是全局约定。

### 三、裸 id 列表

```json
"inner_placements": ["minecraft:small_amethyst_bud", "minecraft:amethyst_cluster"]
```

紫水晶晶洞里成簇生长的方块藏在这里，既不是状态对象也没有 `state` 类键名。
按逐键列举（`inner_placements`、`blocks`），不用后缀通配——枚举会随版本漏，
通配会误收约束类键。

### 四、值是方块标签

```json
"to_place": { "type": "minecraft:random_block", "blocks": "#minecraft:corals" }
```

标签名不是方块，条目也不是一个具体方块，必须在 IR 侧展开。**这一步是语义，
不是语法**，所以适配器只记 `{"slot": "tag", "id": "minecraft:corals"}`，
展开放在 `compile_worldgen`。

## 标签放置怎么展开

```
tag:block/minecraft:corals     ←seeds←    world:minecraft:overworld
block:minecraft:brain_coral    ←implies←  tag:block/minecraft:corals
```

存在性语义使每个成员都判为真：世界无限，只要生成条件非空就必然出现足够
多次。随机选择意味着每个成员被选中的概率非零，于是每个成员都能在某处生成。这跟
「定义了就是有」是同一条语义，不是新规则。

标签展开只适用于放置类标签。约束类标签（`cannot_replace`、`invalid_blocks`、
`geode_invalid_blocks`）说的是「什么可以被替换」，不是「什么会生成」；照它们展开
会把基岩、空气判成可获取。适配器用 `TAG_PLACEMENT_KEYS` 逐键列举，不用后缀通配。

标签不存在或展开为空时返回空，调用方计入 `unresolved_refs['tag']`，不产出一条
永不成立的规则。

## 后果

- 世界生成规则成规模产出；标签放置只在
  `worldgen/feature/coral/block_decoration` 里出现（`minecraft:corals` 与
  `minecraft:wall_corals`）
- `azalea`、`brain_coral` 整族从「自指成环」变为可达
- 引用去重后 `slot_counts` 与 `unresolved_refs` 才反映真实未知量——同一份 JSON 里
  同一个引用会被「状态对象」与「键名」两条路径各取一次
