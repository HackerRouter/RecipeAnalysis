# ObtainableAnalysis

Minecraft 原版物品获取路径分析器。输入一个版本的服务端 jar 与它的反编译源码，输出全部物品的可获取性判定：可获取的给出从初始条件到它的路径，不可获取的给出可复算的归因。

三个问题对应三条命令：

| 问题 | 命令 | 产物 |
|---|---|---|
| 这个物品拿得到吗？经由什么？ | `oa why --label <label> <物品>` | 证明链（可达）或归因与缺项（不可达） |
| 哪些物品拿不到，为什么？ | `oa run --label <label>` | `reachability.jsonl` / `gaps.jsonl` |
| 这个版本的数据长什么样？ | `oa guide --label <label>` | `guide.md` |

范围到「能否获取、经由什么」为止：难度、代价与排序属于下游，本项目不输出。

## 环境配置

| 依赖 | 何时需要 |
|---|---|
| Python 3.11+ | 始终 |
| JDK | `oa inputs init` 首次派生 data 时需要（datagen），版本按 jar 指定 |
| Graphviz 的 `dot` | 只有 `oa-paths` 出图时需要，分析链路不需要 |
| pytest | 只有跑测试时需要，随 `.[dev]` 安装 |

### Python

```bash
python -m venv .venv
source .venv/bin/activate        # Windows：.venv\Scripts\activate
pip install -e .

# 需要运行测试时再安装开发依赖
pip install -e ".[dev]"
```

本文其余命令假定虚拟环境已激活，因此直接写 `python` / `pytest` / `oa`。未激活时使用解释器的完整路径（Windows 为 `.venv\Scripts\python.exe`，其他平台为 `.venv/bin/python`）。

### Java

datagen 的类要求特定 Java 大版本，版本不符时抛出 `UnsupportedClassVersionError`；所需版本由 jar 内 `version.json` 的 `java_component` 决定。每个版本在 `inputs/manifest.toml` 中显式指定一个 JDK：

```toml
["26.3"]
"java_home" = "path/to/jdk-25"
```

`java_home` 可填 JDK 根目录，也可直接填 java 可执行文件的路径。项目不探测 Java 位置，也不回退到 PATH：PATH 上的通常是其他版本，静默误用比直接报错难查。未指定或版本不符时数据导出直接报错停止。

所需版本号与 jar 是否为 bundler 外壳均由程序自行校验，取法见 [`docs/datagen.md`](docs/datagen.md) 的「输入的获取与校验」。

## 运行

### 准备输入

需要准备两项内容。

- **服务端 jar**：从 Mojang 版本清单取得 `server` 下载项，放到 `inputs/<label>/server.jar`，或在执行时用 `--jar` 指定路径。
- **反编译源码**：从服务端 jar 反编译得到的 Java 源码。以下两种方式选一种。
  - 独立整棵：放在 `inputs/<label>/java/`，根下即 `net/minecraft/...`。
  - 反编译源码仓：在 `inputs/manifest.toml` 写仓库位置与版本提交号，由 `oa inputs init` 导出到 `inputs/<label>/java/`。

两项就位后执行：

```bash
oa inputs init --label 26.3 --jar <jar 路径>
```

其余内容由 jar 派生，不需手工放置。不给 `--label` 时只对齐配置并列出已有输入包。

反编译源码仓的写法如下，`[source]` 段在顶层，提交号写在各自的版本段：

```toml
[source]
repo = "path/to/source-repo"          # 相对仓库根，或绝对路径

["26.3"]
content_commit = "c1fd2a862"
"java_home" = "path/to/jdk-25"
```

导出用 `git archive`，不 checkout，也不建工作树。Java 源码根的位置由特征文件 `net/minecraft/WorldVersion.java` 定位，因此仓库的目录组织不影响定位（`src/main/java`、裸 `net/`、多层前缀均可）。一个提交中含多份并列反编译源码树时报错并列出候选，由该版本段的 `source_path` 指定。

不配 `content_commit` 时直接使用手放的 `inputs/<label>/java/`，provenance 记 `null`。已有 `java/` 若不是本工具导出的，视为第一手内容，不会被静默覆盖；改用仓库导出需显式加 `--force`。

datagen 的参数与产物形态见 [`docs/datagen.md`](docs/datagen.md)。

### 命令

```bash
oa inputs init  --label <label> [--jar <jar 路径>]                    # 校验输入、对齐配置、派生 data
oa probe        --label <label>                                      # 探测：目录归属、方言、世界生成来源、未决项
oa ingest       --label <label>                                      # 事实化：数据包与 reports → 事实 + 台账
oa run          --label <label>                                      # 事实 → 规则 → 不动点 → 可达性报告
oa why          --label <label> <节点>                               # 追踪单个物品的获取途径或归因
oa graph        --label <label>                                      # 把全量关系图落成内部表示（可视化用）
oa guide        --label <label>                                      # 把探测与产物结论写成该版本的适配指南
```

从零到一条结论的最短序列（每步的产物是下一步的输入，可单独重跑）：

```bash
oa inputs init --label 26.3 --jar <jar 路径>     # 对齐输入
oa probe       --label 26.3                     # 判目录与方言，未决项在此暴露
oa ingest      --label 26.3                     # 逐文件读成事实，每个文件留一行台账
oa run         --label 26.3                     # 求不动点，写可达性与缺口
oa why         --label 26.3 minecraft:emerald   # 问一个具体物品
oa guide       --label 26.3                     # 这个版本的适配结论
```

可视化是**独立命令** `oa-paths`（不在 `oa` 下），见下节「[路径图](#路径图)」。

`probe --strict` 与 `ingest` 在存在未决项时返回非零，供 CI 使用；`ingest --allow-unknown` 先产出报告再报错。

`oa why` 对可达物品列出全部顶层途径，并逐层展开到 `assume:` / `world:` 起点；对不可达物品给出归因、缺项与规则来源。中间节点默认每条只展开一条子路径，同时报出「另有 N 条」，以免读者误认为该步骤只有一种来源。

### 路径图

可视化是**独立命令** `oa-paths`（不在 `oa` 下）：消费 `oa graph` 的产物，需要 Graphviz，不参与分析管道——缺 `dot` 的人仍能跑完整条链。建图与画图分两步，中间是一份 `graph.json`。为什么这样拆、内部表示存什么、参数与目标高亮怎么定位，见
[ADR 0020](docs/adr/0020-graph-representation-and-rendering.md)。

```bash
oa graph --label 26.3                                  # 写 output/26.3/graph.json（规则 + 三值状态 + 种子）
oa-paths --graph output/26.3/graph.json minecraft:emerald
```

`oa-paths` **只读内部表示文件**，不碰 `inputs/`、不重算规则与不动点，所以同一份数据可以换参数反复画。参数分三类：减噪（`--merge-isomorphic` / `--merge-leaves` / `--group-min`）、展开（`--expand-tags` / `--expand-conditions` / `--expand-groups`）、预算（`--depth` / `--branches` / `--max-nodes` / `--max-groups`）。减噪与预算不互相压制：被预算挡住的成员仍计入同构折叠判据，所以 `--branches 4` 下加 `--merge-isomorphic 3` 仍会收起 13 种木台阶。

`world` / `assume` 这类全局起点默认不单独画：起点写进产物节点的标签第二行（`草方块 / 结构放置·abandoned_camp · 主世界生成`），`--keep-roots` 可恢复成独立节点。

标签的汉化边界：**类别汉化，内容名保持原名**（`玩法掉落 · cat_morning_gift`）——结构名与表名有几千个且随版本增减，译名表必然不全，统一用原名还能直接对照数据包路径查证。

图上的剪枝与折叠一律有标注：预算截断是橙色便签，`tag` 成员与条件写进标签并计数，`body` 含 `FALSE` / `UNKNOWN` 的途径是红色便签报数、不画边；生成参数以原始命令行形式全量写进 HTML 文字区。目标物品用琥珀色双框加粗，其余节点都是它的来源。

只出 `.dot` / `.svg` / `.html`。SVG 是矢量，覆盖拖动、缩放与打印。

### 产物

产物在 `output/<label>/`：

| 文件 | 内容 |
|---|---|
| `profile.json` | 探测结果、jar 摘要、reports 摘要、Java 版本 |
| `facts/<种类>.jsonl` | 事实，每条带 `prov` 与 `status` |
| `ledger.jsonl` | 每个输入文件一行：`parsed` / `classified_skip` / `failed` |
| `facts-summary.json` | 计数、状态分布、按族覆盖率、跳过规则统计 |
| `coverage.json` / `reachability.jsonl` / `gaps.jsonl` | 规则覆盖、逐节点状态、不可达项与归因 |
| `graph.json` | 全量关系图的内部表示：规则 + 三值状态 + 种子（`oa graph` 生成） |
| `paths_<label>_<物品>.{dot,svg,html}` | 单个物品的来源图（`oa-paths` 生成） |
| `guide.md` | 该版本的适配指南：目录归属、形状、未归属项、族级不可用（`oa guide` 生成） |

文件数、可达率这类随输入变化的数字一律现场从产物读取，不写入仓库内的文档。适配新版本时先读 `guide.md`，再对照 [`docs/shapes.md`](docs/shapes.md) 的判据。

## 工作原理

两类输入材料：服务端 jar 提供运行期导出（注册表全集、默认组件、方块属性）与内层二进制结构模板；反编译源码提供数据包 JSON 与 Java 源文件。游戏代码没有公开的原始源码，本项目只需反编译结果。

| 步 | 命令 | 做什么 |
|---|---|---|
| 探测 | `oa probe` | 判定目录对应哪个注册表、数据包方言、世界生成归属与结构模板位置 |
| 事实化 | `oa ingest` | 逐文件读出结构化记录，每个输入文件在台账留一行 |
| 编译与求解 | `oa run` | 事实 + 知识表 → Horn 规则 → 三值最小不动点 |
| 解释 | `oa why` / `oa guide` | 证明链、归因、版本适配指南 |

判据是内容的形状而非版本号，见 [`docs/shapes.md`](docs/shapes.md)。事实种类、链接种类与节点排序是固定集合，构造时校验，新增属契约变更。

事实之间的关系以 Horn 规则描述（`head ← body`）：多条同 head 的规则表达 OR，`body` 表达 AND。求解层只处理这个形式，不认识熔炉——新增数据来源只需在 `ir/families/` 增加一个链接产生器。

可达性采用存在性语义：世界生成中已定义的物品即认为存在某个世界使其出现，因此不判定群系是否可达，也不计算投放间距与密度。

## 开发

- 贡献流程（环境、测试、代码风格、提交改动）见 [`CONTRIBUTING.md`](CONTRIBUTING.md)
- 分层职责，以及新增版本 / 适配器 / 知识表 / 族 / 测试的落点，见 [`docs/development.md`](docs/development.md)
- 纪律与红线（版权边界、事实纪律、只读约束、文档归属）见 [`AGENTS.md`](AGENTS.md)，代理会自动加载

## 目录与文档

| 路径 | 内容 |
|---|---|
| [`docs/`](docs/) | 规格与设计决策（`adr/`） |
| [`knowledge/`](knowledge/) | 人工知识表：假设、词汇、机制、例外 |
| [`src/oa/`](src/oa/) | 实现：inputs / probe / facts / adapters / ir / solve / report |
| [`tests/`](tests/) | 分组测试 |
| [`tools/`](tools/) | 一次性脚本 |
| `plan/` `ref/` `inputs/` `output/` `.cache/` | 方案草稿、只读事实源、输入包、产物、缓存，均不入版本库 |

根目录三份文档的分工见上文「开发」一节；各目录内的文件说明见该目录的 `README.md`。
