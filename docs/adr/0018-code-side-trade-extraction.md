# ADR 0018：代码侧交易提取的完整性与前提对齐

- 状态：已采纳
- 日期：2026-11-03
- 相关：`src/ra/adapters/source/idioms/trades.py`、`docs/adr/0007-trades-family.md`、
  `docs/adr/0017-wandering-trader-assumption.md`、`docs/shapes.md`

## 背景

1.18.x 的交易表硬编码在 `VillagerTrades.java` 里，由 idiom 提取。这套提取器有三处
让它系统性少抽，且都不报错：

| 问题 | 后果 |
|---|---|
| 只登记了 2 个交易类（`ItemsForEmeralds`、`EmeraldForItems`） | 其余 8 类整类丢失：附魔书、藏宝图、药箭、烤鱼、染色皮甲、迷之炖菜、按村民类型换船 |
| `OfferShape` 只能表达**一个**支付物 | 附魔书要绿宝石 + 书、藏宝图要绿宝石 + 指南针，这类交易根本无法表达 |
| 只扫 `hashMap.put(VillagerProfession.X, …)` | 流浪商人的交易表是独立的 `WANDERING_TRADER_TRADES`，整批 68 条漏掉 |

还有一处更严重的：交易链接把村民写成 `via=entity:minecraft:villager`，求解器因此
要求该实体可达。而它在两个版本都零规则、状态 FALSE（结构生成村民这条链没有提取），
于是**整批交易规则恒假**——1.18.2 只有 897/1101 可达，比数据包形态的 26.3 少 11 个
百分点，附魔书、藏宝图一律不可达。

## 决定

### 1. 支付侧是列表，不是单值

```python
OfferShape(give=(Stack(...),), pay=(Stack(...), Stack(...)), basis="…")
```

`Stack` 的四个来源各自有判据：实参下标、类内常量、实参里的 `Map` 字面量、数量。
`Elite` 的三种「付什么」都靠它表达，不靠猜。

### 2. 有重载的类按实参数分派

`ItemsAndEmeraldsToItems` 6 参重载把 `emeraldCost` 折叠成 1，`to/toCount` 在
arg2/arg3；7 参重载显式给出，整体后移到 arg3/arg4。按 6 参读 7 参会把绿宝石
数量当成物品名。判据是实参个数，不是版本号。

### 3. 支付物是 Map 时展开成多条

`EmeraldsForVillagerTypeItem(1, 12, 30, ImmutableMap…put(PLAINS, OAK_BOAT)…)` 是
「每种村民用地的一种船换绿宝石」。只取第一项会漏掉其余类型，所以产出一条
规则对应一个 value。

### 4. 流浪商人的交易表单独扫

`WANDERING_TRADER_TRADES = VillagerTrades.toIntMap(ImmutableMap.of(1, new ItemListing[]{…}, …))`
不在 `TRADES` 区域里。找不到这张表必须留痕，否则「流浪商人卖什么」会静默变成
「没有这种交易」。

### 5. 村民用假设节点，与数据包形态同一前提

```python
Link(head=…, via=(), inputs=("assume:villager_trade", "item:emerald", …))
```

按 `profession` 选 `assume:villager_trade` 或 `assume:wandering_trader`
（[ADR 0017](0017-wandering-trader-assumption.md)）。这与数据包族
（[ADR 0007](0007-trades-family.md)）完全一致：交易能否发生是**前提**，
不是要递归求可达的物品。

### 6. 产出物带随机属性时只记 meta

附魔书、药箭、染色皮甲、附魔装备的产出 id 不变，属性随机。规则判的是
「能不能拿到这本书」，不是「拿到哪一条附魔」；属性写进 `meta.give_variant`。
拆成 `enchant:*` 节点会把「随机附魔」误说成「确定附魔」。

## 换一种做法会错在哪

- **继续让 `entity:villager` 当前置**：整批交易恒假，而错误只表现为可达性偏低，
  没有任何报错。数据包形态与代码形态对同一机制判定相反，是最难查的一类不一致。
- **按类名猜方向**：`EmeraldForItems` 是「用物品换绿宝石」，名字读起来是反的。
  唯一可靠依据是 `MerchantOffer` 的参数顺序（ADR 0007 已记）。
- **用 `Items.ENCHANTED_BOOK` 配 `enchant:*` 节点**：附魔是随机的，写成确定附魔
  会凭空造出一条「这本书有精准采集」的假事实。
- **把 `NOT_A_LISTING` 当作可以忽略的噪音直接跳过**：`ItemStack`、`MerchantOffer`
  出现在交易数组里是正常写法（匿名 `ItemListing` 的 `getOffer` 体），但**必须显式
  登记理由**，否则真正的「未登记交易类」会和噪音混在一起看不出。

## 后果

| 指标 | 1.18.2 改前 | 改后 |
|---|---|---|
| `code/villager_trades` 规则 | 250 | 364 |
| 覆盖的交易类 | 2 | 10 |
| 流浪商人交易 | 0 | 68 |
| 物品可达 | 897/1101 = 81.5% | 921/1101 = 83.7% |

新增覆盖的具体货物：附魔书、藏宝图、药箭、烤鱼、烤鲑鱼、染色皮甲、迷之炖菜、
按村民类型换的六种船（其中的可获取部分）。

`entity:minecraft:villager` 在两版仍零规则、FALSE。这是**另一个**缺口：结构生成的
村民没有被提取。它不再影响交易判定，但「生物实体从哪来」这条链仍然缺一段。
