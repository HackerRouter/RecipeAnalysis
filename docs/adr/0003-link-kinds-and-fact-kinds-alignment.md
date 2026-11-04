# ADR 0003：链接种类向 12 种收敛，`profile` 事实化，`pack_delta` 显式登记

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/ra/adapters/source/idioms/base.py` 的 `LINK_KINDS`、
  `src/ra/adapters/probe_facts.py`

## 背景

数据层跑通后逐条对账，发现三处产物与契约不一致——都不是「实现细节没做完」，
而是产物与契约不一致，越晚修代价越大：

1. `code_link` 用了词汇表外的种类（`place`、`drops`），各自几百条
2. `pack_delta` 一条也不产出，且无任何说明
3. `profile` 声明为事实种类却从未产出

第 2、3 项都违反红线 3：扫描不到的东西不得静默跳过——「一条也没有」在产物上与
「实现漏了」无法区分。

## 决定

### 1. 词汇表落成代码常量并强制校验

`LINK_KINDS` 在 `adapters/source/idioms/base.py`，`Link.__post_init__` 越界即
`ValueError`。产出侧只用 `places` 与 `yield`，不用 `place`（少个 s，属笔误性质的漂移）
与 `drops`（实体装备掉落与 `entities/*` 战利品表同构，都是「产出者 + 条件 → 物品」）。

**为什么硬失败而不是警告**：编译层只认这 12 种。自造词意味着编译层需要一张翻译表，
翻译表漏一项即静默丢失规则边，而丢失了哪些边在产物上不可见。

守卫：`test_kinds_are_from_the_twelve`。

### 2. `pack_delta` 无输入时走 `mark_unavailable`

```python
store.mark_unavailable(
    "pack_delta",
    "本次输入不含地形包",
    "无 packs/ 输入时该族不产出，不代表实现缺失",
)
```

`mark_unavailable` 不落台账行（没有文件就没有行），只进 `facts-summary.json` 的
`unavailable_families`。

### 3. `profile` 产出为事实

新增 `adapters/probe_facts.py`，一条事实，`prov.input = "src"`、`prov.file = "data/"`。

payload 只承载**决定分派**的判定，不复制全量 Profile——完整 Profile 仍留在
`profile.json`。两处分工是「事实流里放判定，快照里放细节」，避免各存一份全量而慢慢
分叉。

`profile` 不对应单个输入文件，因此**不落台账行**——台账的语义是「每个输入文件一行」。

## 两条追加判据

落地后跑通两版，发现两处「产物看着对、语义已错」。

### `min_hits` 不能当硬下限

命中数下限的本意是**防解析退化**，不是「本版必须这么大」。机制随版本搬家会让合法
命中数远低于另一版本，此时按硬下限判族不可用是错的——事实完全可用。

| 命中数 | 处理 | 理由 |
|---|---|---|
| 0 | `mark_unavailable` | 族级不可用，下游确实不能用 |
| >0 但 < `min_hits` | `store.extra["low_yield_idioms"]` | 事实可用，只是规模变化，留待人工看 |
| ≥ `min_hits` | 无动作 | |

### 台账说明行的键必须是业务标识

键不能含序号或行数——序号随插入位置变化，任何一次聚合或重排都会让全部旧键消失，
漂移检测于是把正常重构报成大批文件消失。

判据：一个 idiom 一行，键固定为 `<idiom:{id}>`，多条说明折叠——前若干条保留原文
（「哪些文件没解析出东西」本身是线索），其余归并为计数。

这也说明漂移检测的价值：它能发现「键设计不稳定」这类只有跨运行才暴露的问题。

## 后果

- `code_link` 的种类集合回到 12 种以内，阶段二编译不需要翻译表
- 事实种类 13 类里 `profile` 有产出、`pack_delta` 有明确登记，没有「空且无说明」的族
- 台账不因「非方块物品」膨胀：`place_source` 的说明行聚合为单行而不是逐行展开
