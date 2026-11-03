# ADR 0017：流浪商人单列一条假设

- 状态：已采纳
- 日期：2026-11-03
- 相关：`src/oa/ir/families/trades.py`、`knowledge/assumptions.toml`、
  `docs/adr/0007-trades-family.md`

## 背景

[ADR 0007](0007-trades-family.md) 把全部交易挂在同一个假设节点上：

```
item:X  ←yield←  assume:villager_trade + item:付款物
```

这条规则对职业村民成立：村庄必然存在、村民会补货，交易可重复进行。但
`villager_trade/wandering_trader/` 下的交易不是同一件事——流浪商人随机生成、
不补货、不依赖村庄与工作站。两者共用一个假设节点带来两个问题：

1. `knowledge/assumptions.toml` 的 `basis` 只能写其中一边。写在村民这边，
   对流浪商人就是假的依据；写宽到兼容两者，等于把两条不同的前提糊成一句
   无法审查的话。
2. `survival = false` 的意义是「观察去掉该前提后会失去什么」。混在一个节点上，
   就没法单独问「没有村庄还能拿到什么」——这一问的答案里，流浪商人那部分
   本来是照样能拿到的。

## 决定

**按 `profession` 选前提节点：`wandering_trader` 用 `assume:wandering_trader`，
其余职业共用 `assume:villager_trade`。**

判据只用事实里已有的字段，不建职业清单：

| profession | 前提节点 | 依据 |
|---|---|---|
| `wandering_trader` | `assume:wandering_trader` | 随机生成，售完不补 |
| 其余 | `assume:villager_trade` | 村庄存在，会补货 |

职业与等级仍不进 `body`（ADR 0007 的理由不变）：它们不构成新的获取前提。

## 换一种做法会错在哪

- **继续共用一个节点**：`basis` 必然对其中一边不成立，而假设清单的用途正是
  「进输出、可审查、可单独关闭」。依据失真的假设不满足第一条。
- **按 15 个职业各分一个节点**：职业之间没有前提差异——它们都要村庄与工作站、
  都会补货。拆开只会让同一个前提重复 14 次，且每关一个就要关 14 次。
- **用 `level is None` 判流浪商人**：等级缺席是目录结构的副产品，不是商人类别
  的证据。判据必须是 `profession` 本身。

## 后果

- 播种集多一个节点。两条假设都是 `survival = true`，所以可达性结论不变；
  单独把 `wandering_trader` 置为 `false` 才能观察它独有的贡献。
- 报告里 `trades_by_profession` 的分组不变（它按职业统计，不按假设）。
