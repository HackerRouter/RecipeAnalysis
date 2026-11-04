# ADR 0016：工具要求从物品组件推导，不写等级表

- 状态：已采纳
- 日期：2026-11-02
- 相关：`src/ra/ir/bridges/harvest.py`、`src/ra/ir/families/loot.py`、
  `src/ra/ir/compile.py`、`knowledge/maps/vocabulary/condition_kinds.json`

## 背景

战利品表只说「掉什么」，从不说「用什么挖」。「绿宝石矿要铁镐」不是战利品表里的
条件，而是方块属性。不接这一层，`item:emerald` 的路径就是「世界里有矿 → 掉绿宝石」，
少了整条工具链。

两种工具要求在数据里形态完全不同：

| 要求 | 表达位置 | 例子 |
|---|---|---|
| 工具等级 | 方块 tag（`needs_stone/iron/diamond_tool`） | 绿宝石矿需要铁镐 |
| 具体工具 / 附魔 | 战利品条目条件（`can_shear`、`can_silk_touch`） | 蜘蛛网需要剪刀或精准采集 |

## 决定

**工具等级从物品的 `minecraft:tool` 组件推导，不建等级表、不建材质清单。**

组件的规则形如：

```jsonc
"minecraft:tool": {"rules": [
  {"blocks": "#minecraft:incorrect_for_iron_tool", "correct_for_drops": false},
  {"blocks": "#minecraft:mineable/pickaxe",          "correct_for_drops": true}
]}
```

`incorrect_for_*_tool` 本身用嵌套表达等级：

```
incorrect_for_wooden_tool  ⊇ [needs_diamond, needs_iron, needs_stone]
incorrect_for_stone_tool   ⊇ [needs_diamond, needs_iron]
incorrect_for_iron_tool    ⊇ [needs_diamond]
incorrect_for_diamond_tool ⊇ []
```

于是「物品 I 能采方块 B 并获掉落」= `B ∈ allows(I) 且 B ∉ denies(I)`。

**只对出现在 `incorrect_for_*` 里的方块产工具要求。** 方块是否需要「正确工具」
这个标记（`requiresCorrectToolForDrops`）不在 `blocks.json` 报告里，也不是任何
事实，无法直接读。用这个判据会少报「石头需要任意镐」这类要求，但不会误报——
给叶片强加锄头要求会让路径凭空多一道工序，比少说更糟。

**合格工具取最弱一档。** 「A 比 B 弱」可直接由数据判定：`denies(A) ⊇ denies(B)`。
拒绝集最大者即最弱集（绿宝石矿只留铁镐；黑曜石留钻石与下界合金，两者拒绝集都空、
不可比，都保留）。`loot` 规则因此每条加上一到两个 `tool:` 节点作为 AND 前置。

**`any_of` 里的硬条件展开成多条同 head 规则。** `any_of(can_shear, can_silk_touch)`
是树叶与蜘蛛网掉落物的真实前置（19 个条目）。IR 只有 AND body 与「同 head 多条
规则」两层，OR 就展开成两条规则。`all_of` 与 `inverted` 不动：前者的 terms 掺了
概率与软条件，后者是否定，都不能当获取前置。

## 换一种做法会错在哪

- **写等级表（`{wooden:1, stone:2, iron:3, ...}`）**：等级序是 Mojang 的内部实现，
  不是数据；26.3 有铜工具、1.18.2 没有，金的等级与木同档而耐久不同。任何硬编码序
  都会在某个版本错一档，而错一档的后果是整类矿石的可达性结论翻转。
- **写「材质 → 物品名」清单**：`gold` 对应的物品是 `golden_pickaxe`，名字不规则；
  且清单会随版本增删材质，漏一个即静默少一条工具。
- **把 `mineable/*` 标签当要求**：泥土在 `mineable/shovel` 里，但徒手也能挖。
  用它当判据会给大量方块的路径塞进不必要的工具，而「多余的工序」在可达性上
  看不出来，只在报告里误导人。
- **把 `any_of` 当 combinator 丢掉**：树叶与蜘蛛网会变成「随便挖就掉」，
  路径缺一整条条件，而可达性结论碰巧仍为真，所以这个错误不会被状态数发现。
- **把合格工具逐一枚举**：绿宝石矿三个、石头七个，图上并列一堆镐子，
  读者无法判断「至少要什么」。最弱集把「门槛」这一个信息表达出来。

## 判据

- 工具要求只在 `harvest.capabilities` 里，键是方块注册名，值是最弱合格工具节点。
- 每条 `blocks/<方块>` 的 loot 规则 body 含该方块的工具要求；其它表不含。
- 输入没有物品组件（1.18.2）时整族不可用，必须记进编译期 notes，
  不得静默产出「无工具要求」的路径。
- 组件读不懂（既无 allows 也无 denies）的物品逐个登记，不跳过。
- OR 组合数超过上限时整条条目放弃展开并记 `combinator_overflow`，
  不静默截断某个选项。
