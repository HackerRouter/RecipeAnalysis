# ADR 0010：测试框架用 pytest

测试需要「只跑某几个版本」的能力，因为输入包按版本提供，每个版本都可能只跑自己那一侧。

## 为什么不是 unittest

unittest 的 argparse **没有注册自定义参数的钩子**（pytest 有 `pytest_addoption`）。另一种做法是用 `-k` 匹配测试名子串，但它脆弱：带版本号的类名与不带版本号的跨版本测试混在一起，`-k 263` 会误匹配任何含该数字的名字。

于是版本过滤只能走环境变量。环境变量本身可用，但**把入口能力绑定在环境变量上会带来隐性状态**：设过之后忘记清，后续所有测试都受影响，而失败信息里看不出是被过滤了还是真缺输入包。

| | unittest | pytest |
|---|---|---|
| 自定义参数 | 无扩展点 | `pytest_addoption` |
| 参数化 | 靠基类加手写循环 | `@pytest.mark.parametrize` |
| 失败信息 | 要 `--locals` 才显示局部变量 | 默认显示 |

「纯标准库」在这里不是硬约束：测试本来就要输入包与 Java 运行时，多一个纯 Python 包不构成新的外部依赖。

关键是 pytest 直接收集 `unittest.TestCase` 子类，因此切换是**增量的**——现有测试一行不改，不是二选一的重写。

## `--label` 必须在 collection 之前生效

各测试模块的 `skipUnless(_pack(...), ...)` 在**模块导入时**求值（装饰器位置），版本过滤必须在 collection 之前生效。放到 `pytest_collection_modifyitems` 就晚了——那时模块已经导入、装饰器已经执行完。

因此由 `pytest_configure` 写入环境变量。这是唯一能赶在 collection 之前的钩子。

## 版本清单不硬编码

`support.known_labels()` 扫 `inputs/*/manifest.toml` 得到版本清单。加版本只需放输入包，覆盖检查立刻要求补齐样本，漏补即失败；硬编码版本元组时，新版本缺样本无人报错。

`support.pack()` 未选中返回 `None`，各 `skipUnless` 自动命中。跳过理由用 `why()` / `why_all()` 区分「未选中」与「包不存在」——两者都表现为 skip，但含义完全不同。

## 后果

- 根下 `conftest.py` 承载 `--label`，`support.py` 承载缓存与版本过滤，`golden.py` 是样本数据，说明见 `tests/README.md`
- 目录按项目三阶段分组，单版本跑时跨版本测试静默 skip
- 现有测试保持 `unittest.TestCase` 风格，pytest 直接收集（`subTest` 记为 subtests）
