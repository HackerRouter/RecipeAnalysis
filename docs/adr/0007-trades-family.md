# ADR 0007：交易族与单件工具桥接

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/oa/ir/families/trades.py`、`src/oa/ir/bridges/vocabulary.py`、
  `knowledge/maps/vocabulary/tool_class.json`

## 背景

`trade` 事实在数据包里已有，但 IR 侧没有任何族消费它——族清单里写着「由既有的 `trade`
事实部分覆盖」，实际上一条规则也没编出来。后果是只经交易可达的物品全线不可达：
`filled_map`、五种村庄地图、`ocean_monument_map` 等。

同时 `tool_class` 把剪刀、刷子、打火石、水桶这些单件工具写成 `null`，注释是
「该类没有标签，只能由事实给」。这句话有两处错：

1. 它们不是「工具类」，是具体物品，工具 id 就是物品 id
2. 「只能由事实给」等于永远不给——`tool:minecraft:shears` 一条规则都没有，于是每条
   以剪刀为前置的战利品规则全部为假

## 决定

### 交易族

```
item:minecraft:iron_boots  ←yield←  assume:villager_trade
                                   item:minecraft:emerald
```

- `gives` 是玩家收到的物品，进 `head`；`wants` 与 `additional_wants` 是付款物，进 `body`
- 村民本身用假设节点 `assume:villager_trade`，与 `assume:structure_loot` 同类：
  世界无限、村庄必然存在，但「村庄在哪」不是本项目的推理对象（存在性语义）
- 职业与等级不进 `body`——它们不构成新的获取前提，放 `meta` 供报告展示

> 后续修订：[ADR 0017](0017-wandering-trader-assumption.md) 把流浪商人从这条假设里
> 拆出（前提不同），其余职业仍共用 `assume:villager_trade`；
> [ADR 0018](0018-code-side-trade-extraction.md) 把代码侧形态（交易表硬编码在
> `VillagerTrades`）的前提也改成同一批假设节点，并补齐多支付物与流浪商人交易表。

**形状陷阱**：付款字段可能是**单个对象**也可能**是列表**。直接迭代会取出对象的键名，
于是每条交易都被判成「付款物不是物品」，整族产出 0 条——**不报错**，只表现为
`rule_counts` 为零。判据：先判形状再取值，不要假定容器类型。

`layer == "set"` 的记录是「一级交易集合」的定义，用交易标签引用，里面没有货物。
它们单独计入 `trade_sets`，不计为解析失败。

### 单件工具

`tool_class` 的空值语义为「单件工具」：

```
tool:minecraft:shears  ←implies←  item:minecraft:shears
```

写规则前要对账：物品注册表里必须有同名物品，没有才记 `tools_without_tag`。1.18.2 的
`minecraft:brush` 不存在（该版本还没有刷子），记 `-1`，这是**正确**的留痕。

有标签的类（斧、锄、铲、镐、剑）保持原样走 `tag:item/<标签>`，不枚举物品。

## 后果

- 26.3：`trades` 391 + `trade_sets` 68 = 459，与 `trade` 事实数一致，没有静默丢失
- `bridge/tool` 从 5 条增至 11 条；`glow_lichen` 等依赖剪刀的物品转为可达
- `ir/families/__init__.py` 的族清单与实现一致了
