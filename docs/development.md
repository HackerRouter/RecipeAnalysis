# 开发指南

本文说明分层职责，以及各类改动应落在哪一层。红线与事实纪律见
[AGENTS.md](../AGENTS.md)，提交前的检查事项见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

## 分层的职责边界

三个阶段，各自的输入输出与禁区：

| 模块 | 输入 | 输出 | 不知道什么 |
|---|---|---|---|
| `inputs/` | 用户放的 jar 与反编译源码 | 装配好的输入包、datagen 产物 | 游戏机制 |
| `probe/` | 输入包 | `Profile`：方言、目录归属、能力 | 任何具体内容 |
| `facts/` | —— | 事实与台账的数据结构与 schema | 语义 |
| `adapters/` | 输入包 | 事实 + 台账行 | 可达性、知识以外的游戏规则 |
| `ir/` | 事实 + 知识表 | Horn 规则、种子、统计 | 文件系统、求解 |
| `solve/` | 规则 + 种子 | 三值状态、证明、归因 | 任何游戏知识 |
| `report/` | 求解结果 | `output/` 下的报告与关系图内部表示 | 读 `inputs/` |

可视化（`report/paths/` 的渲染部分）不属这条管道：它是独立命令 `ra-paths`，
消费 `ra graph` 的产物，不参与分析链，且需要 Graphviz。分工的理由见
[ADR 0020](adr/0020-graph-representation-and-rendering.md)。

硬约束：

- **`solve/` 不包含游戏知识**：它不认识熔炉，只知道 `head ← body`。新增机制不得修改求解器。
- **`report/` 与 `solve/` 不读 `inputs/`**：只消费内存中的结构。需要新数据时，先在最上游落成事实。`report/` 读自己产出的中间文件（如 `graph.json`）不算破例——那是产物，不是输入。
- **`adapters/` 只做语法还原**：把 JSON 与反编译源码读成事实，不判断「这条路径是否成立」。语义在 `ir/`。
- **`report/paths/` 的聚合逻辑不进 `solve/`**：来源分类、同构识别、成员层上交都是语义判断，但它们全部由事实里已有的字段（`family` / `meta`）派生，没有新增游戏知识。

## 新增内容的落点

| 目标 | 落点 | 验证 |
|---|---|---|
| 加一个版本 | 放输入包到 `inputs/<label>/`，`ra inputs init` | `pytest --label <label>`；`ingest/test_probe_integration.py` 的 `EXPECTED` 要登记该版本 |
| 加一种数据包来源 | `probe/` 认目录 + `adapters/` 加解析器 | 台账里每个新文件都有行；`facts-summary.json` 计数对得上 |
| 加一种知识 | `knowledge/maps/<category>/<名>.json`，在 `ir/knowledge.py` 读取 | 条目带 `basis`；`knowledge/README.md` 记字段 |
| 加一条机制桥接 | `ir/bridges/` 对应的模块 | 规则数与新增条目数对得上 |
| 加一个来源族 | `ir/families/` 新模块 + `ir/compile.py` 里装配 | `coverage.json` 的 `rule_counts` 出现该族 |
| 加一条代码惯用法 | `adapters/source/idioms/<名>.py` 导出 `exported()`，在 `adapters/source/__init__.py` 的 `default_idioms()` 注册 | 该 idiom 的 `candidate` / `extracted` 计数；锚点必须是**调用形态**而非类名 |
| 加一个黄金样本 | `tests/golden.py` 加一条 `Sample` | 覆盖类别要落在 `tests/ir/test_golden.py` 的 `REQUIRED` 清单内 |
| 改路径图的显示（颜色、形状、类别名） | `report/paths/style.py` | `tests/unit/test_paths_graph.py`；类别键必须仍由 `family` / `meta` 派生 |
| 改路径图的建图或预算 | `report/paths/graph.py` | 同上；剪枝必须有标注，不得静默丢弃 |
| 改路径图的减噪 pass（折叠、压缩、吸收、桶化） | `report/paths/noise.py` | 同上；每个 pass 的计数要能被 `summary.fold_notes` 读到 |
| 改内部表示格式 | `report/paths/store.py` 的 `GRAPH_SCHEMA` +1 | `tests/unit/test_paths_store.py`；旧文件将不可读，属契约变更 |
| 改可视化命令行参数 | `report/paths/cli.py`（独立命令 `ra-paths`） | 参数归入减噪 / 展开 / 预算三类之一 |

### 代码侧提取的留痕层次

反编译源码中识别出的关系不都能成为事实，但每一层都必须留痕：

| 层次 | 含义 | 落在哪 |
|---|---|---|
| `extracted` | 已产出事实 | 事实的 `prov` |
| `candidate` | 疑似存在机制，尚未确认 | 台账逐文件登记 |
| `no_anchor` | 找不到锚点 | 只记规则名与计数 |
| `excluded` | 判定不属于获取关系 | 只记规则名与计数 |

锚点必须是**调用形态**而非类名：同一个类中既有获取关系，也有无关闭包引用，按类名匹配会造成大规模误收。

## 契约变更

以下四项是阶段之间的接口，改动属契约变更，需附 ADR：

| 契约 | 定义处 | 谁在管 |
|---|---|---|
| 事实种类 | `facts/schema.py` 的 `KINDS` | `Fact` 构造时校验 |
| 链接种类 | `ir/nodes.py` 的 `LINK_KINDS`，与 `adapters/source/idioms/base.py` 的同名常量 | `Link.__post_init__` 校验 |
| 节点排序 | `ir/nodes.py` 的 `SORTS` | `node()` 校验 |
| 事实 payload 字段 | 各 `adapters/` 模块的字段白名单 | 未知字段产出 `failed` 事实并记台账 |
| 关系图内部表示 | `report/paths/store.py` 的 `GRAPH_SCHEMA` | `read_graph` 构造时校验，版本不符即失败 |

不得为减少翻译代码而扩充种类：编译层只认固定词汇表，增加一种就要增加一条翻译路径，漏掉一条即静默丢失一条边，而丢失的边在产物上不可见。

## 终端与取证

- 大段输出先写入 UTF-8 文件再读取。终端中截断的中间部分不可信，且 Windows 代码页会使中文输出乱码，判读以文件原文为准。
- `git` 子命令不接受 PowerShell 的通用参数，过滤用管道完成，不用 PowerShell 的开关。
- 用 `RA_LABELS` 或 `--label` 限定版本时，未选中的版本会自动跳过，看跳过理由用 `pytest -rs`。
