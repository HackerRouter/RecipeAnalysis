# 工具脚本

可复算的一次性脚本。

产出落 `docs/` 或 `output/`，不从 `src/oa/` 导入以外的业务逻辑，也不被产品代码调用。

## 目录

| 目录 | 判据 |
|---|---|
| `tools/gaps/` | 追查物品不可获取的原因，按归因或规则形状分类 |
| `tools/probes/` | 取证输入的数据形状，定 schema 之前用 |
| `tools/checks/` | 核对基线与验收条目是否仍成立 |
| `tools/ir/` | 观察编译后的规则与判定链 |

## 在复算链上的

下列脚本被文档引用，改动时需同步：

| 脚本 | 被谁引用 | 验证什么 |
|---|---|---|
| `probes/probe-worldgen-refs.py` | [`docs/shapes.md`](../docs/shapes.md)、[ADR 0005](../docs/adr/0005-worldgen-reference-shapes.md) | 世界生成里方块引用的四种写法 |
| `probes/probe-block-transformer.py` | [`docs/shapes.md`](../docs/shapes.md)、[ADR 0002](../docs/adr/0002-block-transform-fact-kind.md) | 方块转换的字段全集 |
| `checks/check-template-nbt-id.py` | [`docs/shapes.md`](../docs/shapes.md) | 模板 `palette` 的有值项与 `nbt.id` 口径 |
| `gaps/gap-reasons.py` | [`docs/shapes.md`](../docs/shapes.md) | 不可达项的归因分布 |

其余脚本是编写适配器时的取证记录，结论已抽象成 `docs/shapes.md` 与 `docs/adr/` 的判据，脚本本身不作为引用对象。

排查单个缺陷用过的脚本不保留：结论写入判据文档或 ADR，回归由 `tests/` 覆盖。本机环境状态同样不采集：环境属于使用方准备的内容，配置方式写在 [README](../README.md) 的「环境配置」。

## 约定

- 脚本之间互不 import，各自能独立跑
- 路径从 `repo_root()` 或 `Path(__file__).resolve().parents[N]` 取，不写死绝对路径；改动目录层级时后者要同步调整层数
- 大段输出先写入 UTF-8 文件再读取，不用 shell 重定向
- 新增脚本前先确认结论是否属于已有判据；属于则修改该判据，不新增脚本
