# 测试

测试按项目的三个阶段分为若干子目录，集成测试在输入包缺失时自动跳过，不自动联网下载。

## 运行

先装测试依赖：

```bash
pip install -e ".[dev]"
```

命令假定虚拟环境已激活（激活方式见 [README](../README.md#环境配置)）。

| 目标 | 命令 |
|---|---|
| 全量 | `pytest` |
| 单个子目录 | `pytest tests/unit` |
| 只跑一个版本 | `pytest --label 26.3` |
| 只跑跨版本 | `pytest --label 26.3,1.18.2 -k CrossVersion` |
| 单个类 | `pytest tests/unit/test_syntax.py -v` |
| 看跳过理由 | `pytest -rs` |

`--label` 也可用环境变量 `OA_LABELS` 代替（参数优先）。环境变量的设置与清除
看平台（`export` / `$env:` / `set`），它只在当前 shell 会话内有效。

只装了运行时依赖时，`python -m unittest discover -s tests -t .` 仍可兜底，
但版本过滤只能走环境变量。

## 目录

| 目录 | 判据 |
|---|---|
| `tests/unit/` | 跨层的语法、格式与算法单测，不读输入包 |
| `tests/ingest/` | 阶段一数据包侧：探测、适配器、事实化 |
| `tests/code/` | 阶段一反编译源码侧：源码索引与代码惯用法 |
| `tests/ir/` | 阶段二与第三阶段：事实编译成规则、求解、证明、归因 |

各目录单独跑时进程独立、各自摄取，全量跑时摄取缓存跨测试类共享，因此全量耗时小于分次之和。

三个共享文件不属于任何子目录：

- `tests/conftest.py`：pytest 入口，提供 `--label`
- `tests/support.py`：摄取缓存、版本过滤、输入包查找
- `tests/golden.py`：黄金样本表，按版本分元组

## 版本分组

测试分三类，只有第一类需要问「跑哪些版本」：

| 类 | 例子 | 需要几个版本 |
|---|---|---|
| 单版本 | `code/test_drops_source.py` 的 `Drop263Test` 与 `Drop1182Test` | 一个 |
| 跨版本交叉对比 | `code/test_code_link_integration.py` 的 `CrossVersionShearEquivalenceTest` | 必须两个同时在 |
| 与版本无关 | `unit/` 全部 | 零 |

`--label` 是逗号分隔的版本标签，不给则读 `OA_LABELS`，都没有则全选。未选中的版本，`support.pack()` 返回 None，各测试类的 `skipUnless` 自动命中。

过滤在 `pytest_configure` 里生效，早于 collection。这是必需的：各模块的 `skipUnless(_pack("26.3"), ...)` 在**导入时**求值，放到 `pytest_collection_modifyitems` 就晚了。

跳过理由用 `support.why(label)` 与 `support.why_all(labels)`，区分「未选中」与「包不存在」。硬编码理由字符串会使按版本分组运行时被误读为输入包缺失。

版本清单由 `support.known_labels()` 扫描 `inputs/*/` 目录得到，不硬编码。加版本只需放输入包，测试代码不动。

## 断言风格

钉语义，不钉实现细节：

| 断言 | 钉什么 | 为什么不钉 rule id |
|---|---|---|
| `status` | 可达 / 不可达 | — |
| `reason` | 归因类别 | — |
| `family` | 走哪一类来源，前缀匹配 | id 里带文件路径与序号，加一条规则就变 |
| `node_contains` | 证明链里出现哪些节点 | 节点名是 IR 契约，属稳定集合 |
| `missing_any` / `cycle_any` | 缺什么 / 环里有什么 | — |
| `min_alternatives` | 「多路径」这件事本身 | — |

`family` 与 `node_contains` 用可达子图判定而不是证明树。变换族给的是 `block:` 上的规则，只看顶层 `item:` 规则会漏判；`enumerate_proofs` 每个中间节点只展开有限条子路径，组合大时会截断。

黄金样本是数据，断言在 `tests/ir/test_golden.py`。加物品只改 `tests/golden.py` 的 `Sample`，不在断言里写逻辑。

## 加东西

- 加版本：放输入包到 `inputs/<label>/`，再把该版本的探测结论登记到 `ingest/test_probe_integration.py` 的 `EXPECTED`
- 加机制：在对应子目录加测试类；两版共用的断言写成基类，各版本只留 `label` 子类
- 加黄金样本：在 `tests/golden.py` 加一条 `Sample`，覆盖类别要落在 `tests/ir/test_golden.py` 的 `REQUIRED` 清单内

现有测试全部是 `unittest.TestCase` 风格，pytest 直接收集，不需要改。新测试两种风格都可用：需要跨版本参数化时用 `@pytest.mark.parametrize` 比手写基类更短，需要 `skipUnless(_pack(...))` 或黄金样本断言时沿用现有基类。

