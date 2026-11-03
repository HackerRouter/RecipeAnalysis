# ADR 0021：猪灵以物易物由代码事实给出，不走目录假设

## 背景

`knowledge/maps/mechanism/table_providers.json` 按战利品表路径首段挂产出者：

```json
"gameplay": { "kind": "assume", "node": "assume:player",
              "basis": "钓鱼、以物易物、晨礼等玩家动作触发" }
```

`gameplay/` 目录下混着五种互不相干的机制：

| 表 | 实际机制 |
|---|---|
| `fishing` | 玩家钓鱼（要钓竿） |
| `piglin_bartering` | 给猪灵金锭换物品 |
| `hero_of_the_village/*` | 击败袭击后村民送礼 |
| `sniffer_digging` | 嗅探兽挖掘 |
| `chicken_lay` / `panda_sneeze` / `armadillo_shed` / `turtle_grow` / `cat_morning_gift` | 生物被动产出 |

一条目录约定把它们全归到 `assume:player`。后果在路径图上直接可见：黑曜石的
来源标签写成 `玩法 · piglin_bartering`——读者既不知道要付金锭，也看不出这是一
次交易，只能看到一个叫 piglin 的表名。

## 决定

新增 idiom `piglin_barter`，从 `PiglinAi.java` 抽付款物：

```java
public static final Item BARTERING_ITEM = Items.GOLD_INGOT;
LootTable lootTable = ...getLootTable(BuiltInLootTables.PIGLIN_BARTERING);
```

产出 `table:minecraft:gameplay/piglin_bartering ← item:minecraft:gold_ingot`，
金锭进 `inputs`（消耗品，必须递归求可达）。

`mechanics.table_provider_rules` 的取值顺序是**事实优先于目录约定**，这条事实
一旦存在，`gameplay` 那条假设就不再作用于这个表。目录约定本身保留——它仍要覆盖
钓鱼、晨礼等确实没有代码常量的表。

## 换一种做法会错在哪

| 做法 | 错在哪 |
|---|---|
| 把 `gameplay` 整条约定改成 `assume:piglin_barter` | 钓鱼、鸡下蛋被一起挂到猪灵身上 |
| 给 `piglin_bartering` 单开一个目录键 | 路径首段是 `gameplay`，约定按首段匹配，加二级键会让匹配逻辑变成两套 |
| 继续用 `assume:player`，只在图上改标签 | 付款物缺失是数据问题，图上写「猪灵以物易物」反而掩盖了「这条链不需要金锭」这个错误 |
| 把付款物放进 `via` | `via` 的语义是「只需存在不必消耗」，金锭会被当成无限资源 |
| 并进 `trades` idiom | 那是职业 + 等级的定价表；以物易物没有职业、没有等级，付款物是单一常量 |

## 后果

- 两版各 1 条规则（`1.18.2` 与 `26.3` 的 `PiglinAi` 形态一致）
- 黑曜石的路径图上多一条来源 `金锭 --[玩法掉落(piglin_bartering)]--> 黑曜石`：
  **上游是金锭**，与「玩家钓鱼」这类无付款物的 gameplay 表在图上可区分
- `docs/shapes.md` 的 `gameplay` 一节要标明哪张表走事实、哪些仍走约定

图上不再给这个表编中文专名（曾用过「猪灵以物易物」）。展示层只汉化**类别**
（`玩法掉落`），表名保持原名——表名有几千个且随版本增减，译名表必然不全，
不全就变成中英混排。区分靠的是**结构**（它有一个金锭上游），不是靠名字。
