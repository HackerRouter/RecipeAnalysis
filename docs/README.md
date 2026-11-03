# docs/

已定的规格、设计决策与判据。讨论稿放 `plan/`，不入版本库。

按目的找：

| 想做的事 | 读哪份 |
|---|---|
| 跑起来、看产物长什么样 | 根目录 [README](../README.md) |
| 改代码，先确认改动该落在哪一层 | [`development.md`](development.md) |
| 适配新版本，或新增一类数据来源 | [`shapes.md`](shapes.md)，再 [`datagen.md`](datagen.md) |
| 知道某个决定为什么这样定 | [`adr/`](adr/)，一条决策一份 |

| 文件 | 回答什么 |
|---|---|
| [`development.md`](development.md) | 分层职责与各类改动应落在哪一层 |
| [`shapes.md`](shapes.md) | 在哪些位置找数据、按什么形状识别、什么情况下不能认 |
| [`datagen.md`](datagen.md) | 数据生成器的选项、产物形态、输入的获取与校验 |
| [`adr/`](adr/) | 设计决策，一条一份 |

具体某个版本的实测结论不入库，由 `oa guide --label <label>` 从产物生成到 `output/<label>/guide.md`。

新增文档前，先按 [AGENTS.md](../AGENTS.md) 的内容归属表确认落点。
