# ADR 0011：测试框架用 pytest

- 状态：已采纳
- 日期：2026-11-01
- 相关：`tests/conftest.py`、`tests/README.md`、`pyproject.toml`

## 背景

测试需要「只跑某几个版本」的能力：目标是覆盖 1.18.2 到 26.3 之间的主要版本（1.19 /
1.20 / 1.21 / 26.1 / 26.2），每个版本都可能只跑自己那一侧。

unittest 的 argparse **没有注册自定义参数的钩子**（对比 pytest 的 `pytest_addoption`）。
另一种做法是用 `-k` 匹配测试名子串，但它脆弱：`Drop263Test` 带版本号而
`CrossVersionShearEquivalenceTest` 不带，`-k 263` 还会误匹配任何含 `263` 的名字。

于是版本过滤只能走环境变量。环境变量本身可用，但**把入口能力绑定在环境变量上会带来
隐性状态**：设过之后忘记清，后续所有测试都受影响，而失败信息里看不出是被过滤了还是
真缺输入包。

## 决定

选 pytest，理由按重要性：

| | unittest | pytest |
|---|---|---|
| 自定义参数 | 无扩展点 | `pytest_addoption` |
| 参数化 | 靠基类 + 手写循环 | `@pytest.mark.parametrize` |
| 失败信息 | `--locals` 才显示局部变量 | 默认显示 |

「纯标准库」在这里不是硬约束：测试本来就要输入包（jar + 反编译源码树），环境已依赖 Java 运行时
与 datagen，多一个纯 Python 包不构成新的外部依赖。

关键是 pytest 直接收集 `unittest.TestCase` 子类，因此切换是**增量的**——现有测试一行
不改。这不是二选一的重写。

## `--label` 必须在 `pytest_configure` 生效

各测试模块的 `skipUnless(_pack("26.3"), ...)` 在**模块导入时**求值（装饰器位置），版本
过滤必须在 collection 之前生效。放到 `pytest_collection_modifyitems` 就晚了——那时模块
已经导入、装饰器已经执行完。

参数优先、环境变量兜底：不给 `--label` 时读 `OA_LABELS`，两者都没有则全选。保留环境变量
是因为 CI 里设环境变量比传参方便。

## 现有测试不改风格

现有测试保持 `unittest.TestCase` 风格。改写为 pytest 风格收益低：断言内容不变，只是
`self.assertEqual` 换成裸 `assert`，而风险是在改写中丢失 `subTest` 与 `skipUnless` 的语义
（`subTest` 在 pytest 下被正确计为 subtests）。

新测试两种风格都可用。需要跨版本参数化时 `parametrize` 比手写基类短；需要
`skipUnless(_pack(...))` 或复用黄金样本断言基类时沿用现有形态。

## 后果

- `pyproject.toml` 加 `[project.optional-dependencies] dev = ["pytest>=8"]` 与
  `[tool.pytest.ini_options] testpaths = ["tests"]`
- 新增 `tests/conftest.py`
- 全量入口为 `pytest`；`python -m unittest discover -s tests -t .` 仍可兜底
