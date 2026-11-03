# 贡献指南

分层职责与各类改动的落点见 [开发指南](docs/development.md)。

红线与纪律见 [AGENTS.md](AGENTS.md)。

环境配置与命令见 [README](README.md)。

## 环境

按 [README 的环境配置](README.md#环境配置) 建好虚拟环境并安装开发依赖。运行时需要一个 JDK，按版本在 `inputs/manifest.toml` 中显式指定，见 [README 的 Java 节](README.md#java)。

## 测试

`pytest` 跑全量。单版本 `--label` 会跳过跨版本等价性断言，所以提交前必须跑全量。

分组方式、版本过滤与新增测试的规矩见 [`tests/README.md`](tests/README.md)。

## 代码风格

常见 Python 约定不复述。以下几条是本项目自己的约定：

- 每个模块以文档字符串开头，说明该模块的职责与判据；空的 `__init__.py` 除外。
- 公开函数标注参数与返回类型；模块私有的辅助函数可省略。
- 行宽不超过 120 列。
- 校验放在构造时（`__post_init__` 或工厂函数），不留给调用方。
- 不写 `version ==` 分支：两个版本共用同一份代码，差异由探测判定（见 [`docs/shapes.md`](docs/shapes.md)）。

## 提交改动

- 全量 `pytest` 通过。
- 待提交内容符合 [`AGENTS.md`](AGENTS.md) 的版权边界与项目红线：`inputs/`、`output/`、`.cache/`、`ref/`、`plan/` 均已在 `.gitignore` 内。
- 变更描述写明改了什么与为什么改。涉及判据、阈值或边界的改动需附依据，只写结论的改动无法复核。
- 关联相关的 issue 或 ADR。
- 事实种类、链接种类、节点排序与事实 payload 字段的改动属契约变更，需附 ADR；四项的定义处见 [`docs/development.md`](docs/development.md) 的「契约变更」。
