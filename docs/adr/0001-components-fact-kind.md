# ADR 0001：新增 `components` 事实种类

- 状态：已采纳
- 日期：2026-10-30
- 相关：`src/ra/facts/schema.py` 的 `KINDS`、`src/ra/adapters/components.py`

## 背景

默认组件（每个物品的默认数据组件）由运行期导出给出，数据包与 `registries.json`
里都没有。它同时是三条下游推理的前提：item ↔ block 推导（`block` 组件缺失即非方块
物品）、工具/食物/装备分类、变体维度推导（「该组件在默认组件中不是常量」）。

用现有种类表达不了：`registry` 的 payload 是「注册表名 + 条目 ID 列表」，默认组件是
逐条目的属性，形状不同；`profile` 是探测结论（输入长什么样），不是游戏事实。

## 决定

新增事实种类 `components`，一条事实对应一个物品，payload 只记该物品实际具有的组件。
字段定义见 `adapters/components.py`，种类清单见 `facts/schema.py` 的 `KINDS`。

只出现在「有默认组件报告」的版本（1.20.5 起）。1.18.2 不产出这类事实，而由
`FactStore.mark_unavailable` 记一条族级不可用说明——**不用空集合代替「没有组件」**。

## `!` 前缀不能照字面读（重要）

不能把 `!X: {}` 读成「具有 X 且值为空对象」，否则变体维度推导会多出假维度。
**26.3 的默认组件报告里 `!` 前缀 0 处**：表达「不具有」的方式是**键缺席**——每个
物品只列出它实际具有的组件。适配器仍须支持 `!` 写法，判据是键名前缀而不是版本号：
同一份代码要在两个版本上通用。

实现同时接受两种写法：

| 表达 | 处理 |
|---|---|
| 键缺席 | 视为不具有；`absent` 保持为空 |
| `!minecraft:X` | 归入 `absent`，**绝不**进 `components` |

带 `!` 的键即使给了非空值也按「不具有」处理——这正是「把 `!X: {}` 读成『具有 X
且值为空对象』」那个陷阱。同时出现 `X` 与 `!X` 时记入 `problems`。

守卫：`test_bang_prefix_goes_to_absent`、`test_bang_with_non_empty_value_still_means_absent`。

`negation_marker` 记录该物品是否用了 `!` 写法，`profile.notes` 记录该版本整体是否
使用它，便于跨版本观察格式演进。

## 后果

- 事实种类从 10 类变为 11 类
- 下游变体推导可直接使用 `components` 与 `absent`，不需要再读报告文件
