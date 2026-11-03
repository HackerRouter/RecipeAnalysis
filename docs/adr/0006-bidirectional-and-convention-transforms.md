# ADR 0006：变换的反方向与命名约定

- 状态：已采纳
- 日期：2026-10-31
- 相关：`knowledge/maps/mechanism/transform_inverse.json`、
  `transform_conventions.json`、`src/oa/ir/bridges/mechanics.py`

## 背景

`block_transform` 事实记的是**玩家用工具作用于方块**，只表达了「能降级」：

```
block:minecraft:weathered_copper  ←transmutes←  block:minecraft:oxidized_copper  + tool:axe
```

而物品侧想要的是「能升级」。四类物品没有任何对应的正向事实，归因全部落在「自指成环」：

| 物品 | 需要的方向 | 事实里有吗 |
|---|---|---|
| `exposed_copper`（铜族 80 项） | 铜 → 氧化铜 | 没有，氧化是自然过程 |
| `waxed_copper_block` | 铜 + 蜜脾 → 涂蜡铜 | 没有，事实只记除蜡 |
| `red_concrete`（16 色 × 3） | 粉末 + 水 → 混凝土 | 完全没有，不是 Player 动作 |
| `dead_brain_coral` | 珊瑚离水 → 死珊瑚 | 完全没有，方块自身行为 |

## 两条知识表

### 一、`transform_inverse`：按 `sound` 声明可逆性

事实里的 `sound` 是稳定的变换分类标志，同一组方块关系换个前提就是反方向：

| sound | 反方向需要 | 依据 |
|---|---|---|
| `minecraft:item.axe.wax_off` | `item:minecraft:honeycomb` | 涂蜡 |
| `minecraft:item.axe.scrape` | `assume:time` | 自然氧化 |
| `minecraft:item.axe.strip` | — | 剥皮不可逆 |
| `minecraft:item.hoe.till` / `minecraft:item.shovel.flatten` | — | 不可逆 |

没有列进表的 sound 不产反方向规则。**表按 sound 认类，不按方块名枚举**——枚举会随
版本漂移，而 sound 是注册表里的常量。反向规则的 `meta.inverse = true`，报告里可单独统计。

### 二、`transform_conventions`：按词缀配对

固化、脱水、珊瑚死亡这类是方块自身的物理行为，**连变换事实都没有**，只能靠命名约定。

每条约定声明「扫描侧的词缀」与「两侧的名字模板」：

```json
"water_solidify": {
  "match_suffix": "_powder", "head": "{stem}", "body": "{stem}_powder",
  "requires": ["assume:water_source"]
}
"coral_death": {
  "match_prefix": "dead_", "stem_contains": "coral",
  "head": "dead_{stem}", "body": "{stem}", "requires": []
}
```

`stem_contains` 不是装饰：不加它，`dead_` 会命中 `dead_bush`，而 `bush` 是方块，
于是凭空造出「灌木长成枯灌木」。

**两侧都必须命中注册表**才算配对成功，否则记 `miss`。契约里不允许出现「约定生效但
没人知道它没匹配上」的情况。

守卫：`test_convention_coverage_is_complete`、`test_prefix_pairing_and_stem_filter`。

## 后果

- 26.3 实测：`water_solidify` 命中 16 / 配对 16 / 失配 0（`_powder` 在方块注册表里
  只有混凝土粉末）；`coral_death` 命中 20 / 配对 20 / 过滤 1 / 失配 0
- `transforms` 规则量翻倍（多出的是反方向规则）；铜族与混凝土族全部转为可达
  （具体数量由 `oa guide` 给出）
- `bridge/convention` 成为独立家族，`convention_transforms` 覆盖率进 `coverage.json`
