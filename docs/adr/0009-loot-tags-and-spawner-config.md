# ADR 0009：战利品表标签展开与试炼刷怪笼事实

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/oa/ir/families/loot.py`、`src/oa/ir/tags.py`、
  `src/oa/adapters/spawners.py`

## 背景

补完变换、交易、绑定之后，逐个查剩下的 `no_rule`，发现几处**是 bug，不是缺机制**：

| 物品 | 应有来源 | 修前状态 |
|---|---|---|
| 11 张唱片 | `entities/creeper` 表的 `#creeper_drop_music_discs` 标签条目 | 全部 `no_rule` |
| 3 种陶片 | 同一套标签条目机制 | 全部 `no_rule` |
| `breeze_rod`、`mace` | `trial_spawner` 注册表 → `breeze` | `blocked`（实体不在任何事实里） |

## 一、`kind=tag` 的标签名在 `extra.items` 里

26.3 的战利品表里有这样的条目：`kind` 是 `tag`，`name` 是 **null**，标签名在
`extra.items`（`"#minecraft:creeper_drop_music_discs"`）。

编译层当时第一句就是 `if not isinstance(name, str): continue`，于是整条被跳过——
不报错、不记台账，11 张唱片直接消失。

修法：`kind == "tag"` 且 `name` 为空时，从 `extra.items` 剥掉 `#` 取。

## 二、标签条目必须展开成成员

这处更微妙。`tag` 节点在 IR 里只有一个含义：**「其中有任一个」**。`bridge/tag` 编的是
`tag ← item`，方向是「成员真则 tag 真」。

但战利品表的 tag 条目语义是「**从这堆里随机抽一个**」——tag 真之后每个成员都可能产出。
这个方向 `bridge/tag` 给不了：tag 真推不回成员真。修前实测
`tag:item/minecraft:creeper_drop_music_discs` 是 TRUE，而它的 11 个成员全是 FALSE。

所以 loot 族必须把 tag 条目**展开成每个成员各一条**：

```
item:minecraft:music_disc_11  ←yield←  table:minecraft:entities/creeper
```

依据与 worldgen 的方块标签放置完全相同（存在性语义：随机选择 → 每个成员概率非零 →
世界无限 → 每个成员都可能出现）。两处都用同一份成员表，所以把递归展开抽成
`ir/tags.py` 的 `TagMembers`——早先两份实现各自漏过不同写法。

标签不存在或没有可解析成员时记 `unresolved_tag_entries`；成员不在物品注册表时记
`unknown_tag_members`。都不静默。

## 三、试炼刷怪笼是新的事实种类

`trial_chambers` 的结构 JSON 里 `spawn_overrides` 是**空数组**：试炼密室的怪物全部来自
刷怪笼。真正的事实源是 `data/<ns>/trial_spawner/**/*.json`，形状是 `spawn_potentials`
（实体 id + 权重）、`ticks_between_spawn`、`total_mobs`。

新增事实种类 `spawner_config`（契约变更走本 ADR）。只取实体 id 与权重——数量、间隔、
同时存在上限都是**难度**参数，不影响「会不会刷」。

IR 侧接到 `assume:structure_content` 而不是 `structure:trial_chambers`：配置目录名
（`trial_chamber`）与结构 ID（`trial_chambers`）之间没有可复算的映射，硬推一个只会造出
指向不存在结构的节点。

**一个必须一起改的地方**：`skip_inert_registries` 把 `data/<ns>/` 下所有未被 `probe.dirs`
覆盖的目录逐文件登记成「不参与获取路径推理」。新适配器再登记同一批文件就撞台账（实测
报「台账重复登记同一文件」）。所以加 `ADAPTER_DIRS` 白名单，保证「一个目录一个负责者」。

## 四、模板方块实体里装着的物品

饰纹陶罐模板的 `nbt` 里带着陶片 id：三种新陶片**不在任何战利品表里，也不由任何配方
产出**，模板的 `nbt.sherds` 是唯一踪迹。

模板事实新增 `item_refs` 字段（`[{holder, slot, id}]`），IR 编成
`item:X ← block:<holder>`：拆掉陶罐即得。

只取已知键（`sherds` / `Items` / `item` / `Book` / `RecordItem`），不递归猜——方块实体的
`id` 是**方块实体类型**，把它的值当物品会把整棵模板的方块实体都读成物品。

## 五、玩家搭建召唤的实体

凋灵的 `entities/wither.json` 也是空表，它不会自然生成——是玩家按图案摆出来的，所以
没有任何世界生成事实可依。

`knowledge/maps/mechanism/entity_sources.json` 记录这类：

```json
"minecraft:wither": {
  "kind": "summon",
  "requires": ["tag:block/minecraft:wither_summon_base_blocks",
               "item:minecraft:wither_skeleton_skull"]
}
```

成员走 tag 而不是枚举方块：`wither_summon_base_blocks` 的成员由 tag 事实给出。依据是
`WitherSkullBlock#getOrCreateWitherBase` 的 `BlockPatternBuilder`。

同时新增 idiom `death_drops`：实体死亡时 `spawnAtLocation(..., Items.X)` 直接塞一个物品
实体。两版签名不同（26.3 带 `level` 参数、1.18.2 不带），正则让逗号段可选。

## 六、例外表提前生效

`petrified_oak_slab` 有战利品表也有放置桥，两者互指成环，归因是 `cycle_no_entry`——而
该归因暗示「只差一步即可获取」。实际结论是「命令专用，生存不可获取」。

所以 `attribute()` 把例外表检查提到**其余全部归因之前**。物品往往*有*规则，只是那些规则
不成立；先看规则会得到误导性的分类。

`unobtainable` 因此可出现在 `no_rule` 之外的归因里。`suspicious_sand` 是最典型的例子：方块在世界
生成中可达（结构里生成），但战利品表为空，挖除时不掉落本体——方块可生成不等同于物品可获取。

## 后果

- `loot` 规则 2556 → 2568；新增 `bindings/spawner` 与 `bindings/template_item`
- 新增事实种类 `spawner_config`、新适配器 `spawners.py`
- 新增 idiom `death_drops`、`fluid_buckets`；新增知识表 `entity_sources.json`
- `sheep.py` 的节点名必须带命名空间（`tool:minecraft:shears`）：缺命名空间时
  1.18.2 的整条剪毛规则恒假
