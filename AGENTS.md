# AGENTS.md

本文件规定不可违反的约束。与其余文档冲突时以本文件为准；其余文档按本文件的分层与归属规则组织。

输入包是被分析对象，游戏代码的反编译产物只作事实来源。本项目的约束因此是两条：输入只读，产物可复算。

项目目标、用法与目录见 [README](README.md)；开发流程与代码风格见 [CONTRIBUTING](CONTRIBUTING.md)；分层职责与各类改动的落点见 [开发指南](docs/development.md)。

## 版权边界

仓库不保存 Mojang 制品与数据副本：jar、反编译源码、datagen 产物一律不入库，由 `.gitignore` 排除 `inputs/`、`output/`、`ref/`、`.cache/`。

允许保留的是接口标识符（注册表名、`item_id`、组件路径）与本项目自己的分类判断——它们是 schema 的骨架，不是 Mojang 的内容。

## 事实纪律

- 事实只在两处取证：反编译源码仓的提交内容，与服务端 jar 跑出的运行期导出。不引 wiki（只用于定位结构）、不凭记忆、不照搬他处结论。
- 反编译源码按提交号取，不读工作树：工作树停在任意版本。导出走 `git archive`，不 checkout、不建工作树；`inputs/source.py` 对仓库只调用 `ls-tree` 与 `archive`。
- 提交号由用户显式配置（[ADR 0001](docs/adr/0001-inputs-and-source-export.md)）。配成不含 Java 源码树的提交会被导出阶段挡住：反编译源码根按特征文件定位，找不到即报 `InputError`。
- 数据格式随版本演进。适配器对未知字段必须报错，不得忽略；形状判据见 [`docs/shapes.md`](docs/shapes.md)。

## 项目红线

1. `ref/` 只读：不 checkout、不建工作树、不写入、不改工作树状态。
2. 输入包的第一手内容只读：不改用户提供的 `server.jar`、`java/` 与 `datapacks/`。`data/`、`version.json`、`pack.mcmeta`、`java.json`、`datapack-merged/` 是派生，`manifest.toml` 是配置，由 `ra inputs init` 维护。无 `java.json` 的 `java/` 视为第一手内容，覆盖需显式 `--force`。数据包的加载顺序只在配置里定，不改包内文件，也不靠文件名排序静默决定。
3. 扫描不到的东西不得静默跳过，必须显式登记：只有 `type` 的配方、`dynamic` 战利品条目、数据包内无引用点的代码绑定、被更高优先级数据包覆盖或被 `filter` 屏蔽的源文件，一律留痕。
4. 产物必须带 provenance：`run.json` 记录 `jar_sha256`、`ir_schema`、`facts_digest`、`content_commit` 与 `source_repo`。前三项缺失则报告不可复算；提交号未配置时记 `null`，此时代码侧结论不可复算。`graph.json` 只带 `graph_schema` / `ir_schema` / `facts_digest`，能判断是否过期，不能证明来自哪个 jar——引用图上的结论时另引 `run.json`。数据包覆盖生效时，`profile.json` 的 `datapack_merge` 记录每个包的摘要与合并计数，`merge-log.jsonl` 记录逐处覆盖；数据包内容变了，事实就不可比。

## 文档

- 方案与分层放 `plan/`，定稿后迁入 `docs/`。`plan/` 允许自相矛盾，`docs/` 只写已定的事实与规定。
- 规格放 `docs/<主题>.md`；设计决策按主题归并成一份 `docs/adr/`；数据形状的识别判据放 `docs/shapes.md`。
- 结论按当前输入现场生成（`ra guide`），不手抄进文档；写进文档的每个数字都要有固定出处。
- 数据契约随实现落在代码里（事实 schema、IR schema）。字段改动属契约变更，走 ADR。
- ADR 只写「换一种做法会错在哪」与判据。取证过程、进度数字、已被代码与测试钉住的守卫不留在正文；确需保留的历史判断放 `ref/history/`。
- 同一内容只写一处，其余用链接指向。指向 `plan/` 的章节号不构成指针，它不入版本库。
- 内容归属按性质判定：

  | 内容 | 落点 |
  |---|---|
  | 某个版本的数据长什么样 | `ra guide --label <label>` 产出，不入版本库 |
  | 数据形状的识别判据（跨版本） | `docs/shapes.md` |
  | 项目怎么规定（判据、取舍） | `docs/<主题>.md` 或 `docs/adr/` |
  | 一次性取证过程 | 不入版本库，或存 `ref/history/` |
  | 机制分类 | `knowledge/maps/` |
