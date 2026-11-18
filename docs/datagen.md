# 数据生成器参数

`net.minecraft.data.Main` 是 jar 内的数据生成器入口。bundler jar 的 `-jar` 主类是 `net.minecraft.bundler.Main`，datagen 必须自行组 classpath 后用 `-cp ... net.minecraft.data.Main` 启动，classpath 的装配见 `src/ra/inputs/`。

两条产物链各自对应一组参数：`--reports` 出注册表与组件，`--dev` 出结构模板的文本形态。后者是本项目的结构事实来源，原因见[数据形态指南](shapes.md)的「结构模板」一节。

## 选项

26.3 的选项：

| 选项 | 参数 | 作用 |
|---|---|---|
| `--help` | — | 打印帮助。未给任何选项时也打印帮助 |
| `--server` | — | 注册服务端数据生成器：配方、战利品表、标签、进度、注册表、交易，以及 `SnbtToNbt`（SNBT 转 NBT） |
| `--dev` | — | 注册 `NbtToSnbt`：读 `--input` 下的 `.nbt`，写 `.snbt` |
| `--reports` | — | 注册报告：`biome_parameters/`、`minecraft/components/item/`、`blocks.json`、`commands.json`、`datapack.json`、`json-rpc-api-schema.json`、`packets.json`、`registries.json` |
| `--validate` | — | 接受该选项，不参与任何生成器 |
| `--all` | — | 等价于 `--server --dev --reports` |
| `--output` | 目录 | 产物根，默认 `generated` |
| `--input` | 目录，可重复 | 转换器输入根；产物路径相对该根 |

1.18.2 的差异：

- 多一个 `--client`，注册客户端生成器与模型。
- `SnbtToNbt` 在 `--client` 或 `--server` 下运行。
- `NbtToSnbt` 在 `--dev` 下运行。
- `--reports` 额外导出 `worldgen/`，26.3 的 `--reports` 不导出。
- `--validate` 被传入 `createStandardGenerator`，该方法未使用。

`--input` 的根是 `data/` 的上一级。转换器用 `root.relativize(path)` 生成产物名；`StructureUpdater` 只处理以 `data/minecraft/structure/` 开头的名字。`--server` 或 `--dev` 不给 `--input` 时，对应转换器没有输入，不产出任何模板。

## data generator 不处理数据包

数据生成器不是数据包加载器，不能用它代劳覆盖合并。

判据：`Main` 注册的 providers 全部从 `VanillaRegistries` 取注册数据，`--input` 只传给 `SnbtToNbt` 与 `NbtToSnbt`。它不读 `pack.mcmeta`，也没有加载顺序的概念。把数据包根交给 `--server --input` 得到的是被重写的模板，不是合并后的数据包（未改 palette 就报 `Multiple entries with same key`）。

生成器仍被用于两件事：产出运行期导出，以及把模板 `.nbt` 升级并转成 `.snbt`。数据包带入的模板并进同一批转换，因此同样经过 `DataFixTypes.STRUCTURE`。

覆盖语义与落盘位置见 [ADR 0014](adr/0014-datapack-overlay.md)。

## 结构模板的转换方向

`.snbt` 是打包形态，`.nbt` 是展开形态：

| 形态 | `palette` | 格子里的 `state` |
|---|---|---|
| `.snbt` | 方块状态字符串列表 | 引用 `palette` 条目的字符串 |
| `.nbt` | compound 列表 | 整数索引 |

26.3 的二进制 palette compound 用 `id` 与 `properties`；1.18.2 用 `Name` 与 `Properties`。

- `--server`：`SnbtToNbt` 读 `--input` 的 `.snbt`，经 `NbtUtils.snbtToStructure` 解包，再由 `StructureUpdater` 用 `StructureTemplate.load` 与 `save` 重写，输出 `.nbt`。
- `--dev`：`NbtToSnbt` 读 `--input` 的 `.nbt`，经 `DataFixTypes.STRUCTURE` 升级与 `NbtUtils.structureToSnbt` 打包，输出 `.snbt`，顶层写 `DataVersion`。

`NbtUtils.snbtToStructure` 把 palette 字符串映射成 compound，映射表不允许重复键。palette 含多个空字符串时直接报 `Multiple entries with same key`。

## 项目的调用方式

两处调用，按产物分工：

| 模块 | 参数 | 产物 |
|---|---|---|
| `src/ra/inputs/datagen.py` | `--reports` | `reports/`：注册表、默认组件、`blocks.json`、`datapack.json` |
| `src/ra/inputs/structures.py` | `--dev --input <提取的 data 根>` | `structures/`：模板 `.snbt` |

两者共用同一缓存目录（`.cache/<jar 文件名>-<键>/`，键由 jar 摘要与 Java 大版本算出），因此 `bundler/` 只解一次。模板的中间 `.nbt` 转完即删——有 jar 摘要就能完整复算。

模板目录靠形状定位：内层 jar 里全为 `.nbt` 的 `data/<ns>/<sub>` 即模板目录，26.3 命中 `structure/`、1.18.2 命中 `structures/`。

## 验证结果

- `--dev --input <jar 解出的 data 根>`：两版的 `.nbt` 全部转成 `.snbt`，`palette` 项项有值，顶层写入 `DataVersion`。
- `--server --input <输入包的反编译源码树资源根>`：在 `NbtUtils.snbtToStructure` 报 `IllegalArgumentException: Multiple entries with same key`，该目录的 `palette` 全是空串。
- `--reports`：不产出模板，产物根下没有 `.snbt`。

各版本的转换数量与 `DataVersion` 由 `ra guide --label <label>` 与 `output/<label>/facts/template.jsonl` 给出。

复算：

```bash
java="<java 25 的 java 可执行文件>"
cp="<versions jar 与 libraries 组成的 classpath>"

"$java" -cp "$cp" net.minecraft.data.Main --reports --output out
"$java" -cp "$cp" net.minecraft.data.Main --dev --input <含 data/ 的目录> --output out
```

classpath 的分隔符跟平台：Windows 是 `;`，其余是 `:`。

项目内直接用封装后的入口：

```bash
python -c "from pathlib import Path; from ra.inputs import load_manifest, ensure_structures; from ra.paths import cache_root, repo_root; print(ensure_structures(load_manifest(Path('inputs/26.3')), cache_root(repo_root())).as_json())"
```

模板的身份来源与判据见 [数据形态指南](shapes.md) 的「结构模板」一节；某个版本的模板目录与文件数由 `ra guide --label <label>` 给出。

## 输入的获取与校验

服务端 jar 从 Mojang 的版本清单取得（该清单是公开的固定地址，选 `server` 下载），放进输入包后由 `ra inputs init` 校验并装配其余部分。

jar 摘要、reports 产物摘要、Java 大版本要求都是**现场可取的**，不写进文档：

| 项 | 取法 |
|---|---|
| jar 的 `sha256` | `ra probe` 后读 `output/<label>/profile.json` 的 `jar.sha256`；或平台自带的摘要工具 |
| reports 产物摘要 | 同上，`profile.json` 的 `reports.digests` |
| Java 大版本要求 | 同上，`profile.json` 的 `reports.java.version` 与 `component`；源头是 jar 内 `version.json` 的 `java_component` |
| 实际选用的 Java | 同上，`reports.java.path` 与 `source` |

jar 必须是 bundler 外壳（`Main-Class: net.minecraft.bundler.Main`）。不合规时 `ra inputs init` 与 datagen 入口都会直接报错，不需要预先查表确认。

Java 的版本要求与指定方式见 [README 的环境配置](../README.md)。datagen 的耗时与缓存占用随机器变化，不进文档。
