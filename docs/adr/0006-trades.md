# ADR 0006：交易

交易在数据包里有三层结构（交易组、标签、单条交易），在代码侧是一张硬编码表。两处形态不同，但前提与方向必须一致——对同一机制给出相反判定，是最难查的一类不一致。

## 一、数据包形态的规则形状

```
item:minecraft:iron_boots  ←yield←  assume:villager_trade
                                   item:minecraft:emerald
```

- `gives` 是玩家收到的物品，进 `head`；`wants` 与 `additional_wants` 是付款物，进 `body`
- 村民本身用假设节点：世界无限、村庄必然存在，但「村庄在哪」不是推理对象
- 职业与等级不进 `body`——它们不构成新的获取前提，放 `meta` 供报告展示

**形状陷阱**：付款字段可能是**单个对象**也可能**是列表**。直接迭代会取出对象的键名，于是每条交易都被判成「付款物不是物品」，整族产出 0 条——不报错，只表现为 `rule_counts` 为零。判据是先判形状再取值。

`layer == "set"` 的记录是「一级交易集合」的定义，用交易标签引用，里面没有货物，单独计入 `trade_sets`，不计为解析失败。

**一笔交易可以要不止一样东西**：附魔书要绿宝石 + 书、藏宝图要绿宝石 + 指南针。只取第一个付款物会得到「绿宝石换附魔书」，把书这个前提抹掉。

## 二、流浪商人单列一条假设

按 `profession` 选前提节点，其余职业共用 `assume:villager_trade`：

| profession | 前提节点 | 依据 |
|---|---|---|
| `wandering_trader` | `assume:wandering_trader` | 随机生成，售完不补 |
| 其余 | `assume:villager_trade` | 村庄存在，会补货 |

共用一个节点有两个问题：`assumptions.toml` 的 `basis` 只能写其中一边，写在村民这边对流浪商人就是假的依据；`survival = false` 的意义是「观察去掉该前提会失去什么」，混在一个节点上就没法单独问「没有村庄还能拿到什么」。

| 做法 | 错在哪 |
|---|---|
| 按 15 个职业各分一个节点 | 职业之间没有前提差异，拆开只会让同一前提重复 14 次 |
| 用 `level is None` 判流浪商人 | 等级缺席是目录结构的副产品，不是商人类别的证据 |

## 三、代码侧形态的提取

交易表硬编码在 `VillagerTrades` 的版本由 idiom 抽取。五处系统性少抽，且都不报错：

| 问题 | 后果 |
|---|---|
| 只登记两个交易类 | 其余各类整类丢失：附魔书、藏宝图、药箭、烤鱼、染色皮甲、迷之炖菜、按村民类型换船 |
| `OfferShape` 只能表达一个支付物 | 两件付款物的交易无法表达 |
| 只扫 `hashMap.put(VillagerProfession.X, …)` | 流浪商人的表是独立的 `WANDERING_TRADER_TRADES`，整批漏掉 |
| 把村民写成 `via=entity:villager` | 该实体零规则时整批交易恒假 |
| 产出物带随机属性时拆成新节点 | 把「随机附魔」说成「确定附魔」 |

### 支付侧是列表

`OfferShape(give=(...), pay=(Stack(...), Stack(...)))`。`Stack` 的四个来源各有判据：实参下标、类内常量、实参里的 `Map` 字面量、数量。

### 有重载的类按实参数分派

`ItemsAndEmeraldsToItems` 的 6 参重载把 `emeraldCost` 折叠成 1，`to/toCount` 在 arg2/arg3；7 参重载显式给出，整体后移。按 6 参读 7 参会把绿宝石数量当成物品名。判据是实参个数，不是版本号。

### 支付物是 Map 时展开成多条

`EmeraldsForVillagerTypeItem(1, 12, 30, ImmutableMap…put(PLAINS, OAK_BOAT)…)` 是「每种村民用地的一种船换绿宝石」。只取第一项会漏掉其余类型，所以一个 value 一条规则。

### 流浪商人的表单独扫

`WANDERING_TRADER_TRADES = VillagerTrades.toIntMap(ImmutableMap.of(1, new ItemListing[]{…}, …))` 不在 `TRADES` 区域里。找不到这张表必须留痕，否则「流浪商人卖什么」会静默变成「没有这种交易」。

### 村民是假设节点，不是要求可达的实体

```python
Link(head=…, via=(), inputs=("assume:villager_trade", "item:emerald", …))
```

交易能否发生是**前提**，不是要递归求可达的物品。与数据包形态完全一致。

### 产出物带随机属性时只记 meta

附魔书、药箭、染色皮甲、附魔装备的产出 id 不变，属性随机。规则判的是「能不能拿到这本书」，不是「拿到哪一条附魔」；属性写进 `meta.give_variant`。拆成 `enchant:*` 节点会凭空造出一条「这本书有精准采集」的假事实。

### 噪音要显式登记理由

`NOT_A_LISTING`（`ItemStack`、`MerchantOffer` 出现在交易数组里，属匿名 `ItemListing` 的 `getOffer` 体）是正常写法，但必须显式登记理由，否则真正的「未登记交易类」会和噪音混在一起看不出。

## 换一种做法会错在哪

- **按类名猜方向**：`EmeraldForItems(Items.WHEAT, 20, …)` 是「20 小麦换 1 绿宝石」，名字读起来是反的。唯一可靠依据是 `MerchantOffer(costA, result, …)` / `(costA, costB, result, …)` 的参数顺序
- **继续让 `entity:villager` 当前置**：整批交易恒假，错误只表现为可达性偏低，没有任何报错
- **把付款物放进 `via`**：`via` 的语义是「只需存在不必消耗」，会被当成无限资源

## 后果

- 数据包形态与代码侧形态产出同族规则（`trades` / `code/villager_trades`），前提节点共用
- `trades_by_profession` 按职业统计，不按假设
- 未抽到的交易类、未解析的付款物进 `unresolved_trades`，不静默跳过
