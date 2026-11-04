# ADR 0007：方块变换与工具要求

两者都是「方块属性」而非战利品表内容：变换是「拿着 A 对着方块 B 用，B 变成 C」，工具要求是「用什么东西挖才掉」。数据里它们的形态完全不同，且都有「照字面实现会静默多出工序或漏掉整族」的陷阱。

## 一、`block_transform` 事实种类

「拿着 A 作用于方块 B，B 变成 C」的来源随版本不同：

| 版本 | 来源 | 提取途径 |
|---|---|---|
| 旧版本 | Java 静态字段（`AxeItem.STRIPPABLES` 等） | `code_link` 的 idiom |
| 新版本 | 数据包注册表 `data/minecraft/block_transformer/*.json` | 独立事实种类 |

数据包侧是**文件**，形状与 `code_link` 不同：没有 Java 行号，但带 `properties`、`loot`、`drop_strategy`、`item_damage_per_use` 等运行时参数。硬塞进 `code_link` 会让 `prov` 语义混乱（后者的 `prov.file` 是 `.java`）。

一条事实对应**一条变换规则**（不是注册表文件），核心字段 `transformer` / `from` / `to` / `soft`。`prov.ptr` 是该规则在文件里的下标，满足可复算。

**两版共用同一形状**，只差三个字段的取值：

| 字段 | 数据包侧 | 代码侧 |
|---|---|---|
| `transformer` | `minecraft:axe`（注册表 ID） | `net.minecraft.world.item.AxeItem#STRIPPABLES` |
| `transformer_kind` | `registry` | `code_table` |
| `mode` | `rules` | `table` / `inverse` / `color_collection` |

同一种语义不能有第二种形状——这是分层的硬要求，不是整洁偏好。

### `transformer` 不是「谁触发」

它记的是**变换表的位置**：数据包侧是注册表 ID（客观），代码侧是类名（客观）。「哪些物品是斧头」要看 `Items.IRON_AXE = new AxeItem(...)` 这类注册，属 IR 的代理判定。

同理，随机刻氧化与玩家主动剥皮在事实层形状相同，可达性判定留给 IR。

### `from` 与 `soft` 按 `offset` 分流

`all_of` 内的 predicate 有两种用途：

| predicate | 含义 | 归入 |
|---|---|---|
| 无 `offset` | 被转换的源方块（或 tag） | `from` |
| 有 `offset` | 环境前提（「上方是空气」） | `soft`，写作 `above=tag:minecraft:air` |

把带 `offset` 的当源方块，会让「泥土 → 耕地」变成「空气 → 耕地」，路径必然中断。

## 二、反方向靠 `sound` 认类

变换事实只表达「能降级」：

```
block:minecraft:weathered_copper  ←transmutes←  block:minecraft:oxidized_copper  + tool:axe
```

物品侧想要的是「能升级」。四类物品没有任何正向事实：铜族需要氧化、涂蜡铜需要上蜡、混凝土需要水、死珊瑚来自离水。

`transform_inverse` 按 `sound` 声明可逆性——`sound` 是注册表里的常量，稳定：

| sound | 反方向需要 | 依据 |
|---|---|---|
| `minecraft:item.axe.wax_off` | `item:minecraft:honeycomb` | 涂蜡 |
| `minecraft:item.axe.scrape` | `assume:time` | 自然氧化 |
| `minecraft:item.axe.strip` / `minecraft:item.hoe.till` / `minecraft:item.shovel.flatten` | —— | 不可逆 |

没列进表的 sound 不产反方向规则。**按 sound 认类，不按方块名枚举**——枚举会随版本漂移。反向规则的 `meta.inverse = true`，可单独统计。

## 三、无变换事实的物理行为按命名约定

固化、脱水、珊瑚死亡这类是方块自身行为，**连变换事实都没有**，只能靠命名约定。每条约定声明扫描侧词缀与两侧名字模板：

```json
"water_solidify": {"match_suffix": "_powder", "head": "{stem}", "body": "{stem}_powder",
                   "requires": ["assume:water_source"]}
"coral_death": {"match_prefix": "dead_", "stem_contains": "coral",
                "head": "dead_{stem}", "body": "{stem}", "requires": []}
```

`stem_contains` 不是装饰：不加它，`dead_` 会命中 `dead_bush`，而 `bush` 是方块，于是凭空造出「灌木长成枯灌木」。

**两侧都必须命中注册表**才算配对成功，否则记 `miss`。契约不允许「约定生效但没人知道它没匹配上」。

守卫：`test_convention_coverage_is_complete`、`test_prefix_pairing_and_stem_filter`。

## 四、工具要求从物品组件推导

战利品表只说「掉什么」，从不说「用什么挖」。「绿宝石矿要铁镐」是方块属性。不接这一层，路径就是「世界里有矿 → 掉绿宝石」，少了整条工具链。

两种工具要求在数据里形态完全不同：

| 要求 | 表达位置 | 例子 |
|---|---|---|
| 工具等级 | 方块 tag（`needs_stone/iron/diamond_tool`） | 绿宝石矿需要铁镐 |
| 具体工具 / 附魔 | 战利品条目条件（`can_shear`、`can_silk_touch`） | 蜘蛛网需要剪刀或精准采集 |

**工具等级从物品的 `minecraft:tool` 组件推导，不建等级表、不建材质清单。**

```jsonc
"minecraft:tool": {"rules": [
  {"blocks": "#minecraft:incorrect_for_iron_tool", "correct_for_drops": false},
  {"blocks": "#minecraft:mineable/pickaxe",          "correct_for_drops": true}
]}
```

`incorrect_for_*_tool` 用嵌套表达等级：

```
incorrect_for_wooden_tool  ⊇ [needs_diamond, needs_iron, needs_stone]
incorrect_for_stone_tool   ⊇ [needs_diamond, needs_iron]
incorrect_for_iron_tool    ⊇ [needs_diamond]
incorrect_for_diamond_tool ⊇ []
```

于是「物品 I 能采方块 B 并获掉落」= `B ∈ allows(I)` 且 `B ∉ denies(I)`。

**只对出现在 `incorrect_for_*` 里的方块产工具要求。** 「必须用正确工具才掉」这个标记（`requiresCorrectToolForDrops`）不在 `blocks.json` 报告里，也不是任何事实。用这个判据会少报「石头需要任意镐」，但不会误报——给叶片强加锄头要求会让路径凭空多一道工序，比少说更糟。

**合格工具取最弱一档。** 「A 比 B 弱」可直接由数据判定：`denies(A) ⊇ denies(B)`。拒绝集最大者即最弱集（绿宝石矿只留铁镐；黑曜石留钻石与下界合金，两者拒绝集都空、不可比，都保留）。

**`any_of` 里的硬条件展开成多条同 head 规则。** `any_of(can_shear, can_silk_touch)` 是树叶与蜘蛛网掉落物的真实前置。IR 只有 AND body 与「同 head 多条规则」两层，OR 就展开成两条。`all_of` 与 `inverted` 不动：前者掺概率与软条件，后者是否定，都不能当获取前置。

| 做法 | 错在哪 |
|---|---|
| 写等级表 `{wooden:1, stone:2, iron:3}` | 等级序是内部实现不是数据；金的等级与木同档而耐久不同。硬编码序会在某个版本错一档，后果是整类矿石的可达性翻转 |
| 写「材质 → 物品名」清单 | `gold` 对应 `golden_pickaxe`，名字不规则；清单随版本增删材质，漏一个即静默少一条工具 |
| 把 `mineable/*` 标签当要求 | 泥土在 `mineable/shovel` 里但徒手能挖，会给大量方块塞进不必要工具，而多余工序在可达性上看不出来 |
| 把 `any_of` 当 combinator 丢掉 | 树叶与蜘蛛网变成「随便挖就掉」，可达性碰巧仍为真，状态数发现不了 |

## 判据

- 工具要求只在 `harvest.capabilities` 里，键是方块注册名，值是最弱合格工具节点；每条 `blocks/<方块>` 的 loot 规则 body 含该方块的要求，其它表不含
- 输入没有物品组件时整族不可用，必须记进编译期 notes，不得静默产出「无工具要求」的路径
- 组件读不懂（既无 allows 也无 denies）的物品逐个登记
- OR 组合数超过上限时整条条目放弃展开并记 `combinator_overflow`，不静默截断某个选项
