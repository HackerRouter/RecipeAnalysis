# docs/adr/

设计决策按主题归并，一份管一个方面。每份只写「换一种做法会错在哪」与判据——取证过程、进度数字、已被代码与测试钉住的守卫不进正文。

| 文件 | 管什么 |
|---|---|
| [`0001-inputs-and-source-export.md`](0001-inputs-and-source-export.md) | 源码根怎么定位、提交号谁给、版本实测结论放哪 |
| [`0002-fact-and-link-kinds.md`](0002-fact-and-link-kinds.md) | 新增事实种类与链接种类的判据、族级不可用、条目权重与分组、标签条目展开 |
| [`0003-worldgen-and-references.md`](0003-worldgen-and-references.md) | 世界生成里方块引用的四种写法、排序锚定、方块名不在 JSON 里的特征 |
| [`0004-structure-and-template-bindings.md`](0004-structure-and-template-bindings.md) | 模板方块与实体、结构刷怪、结构生成器里的实体、例外表优先级 |
| [`0005-entity-sources-and-behaviour.md`](0005-entity-sources-and-behaviour.md) | 行为产出为什么用声明式表、产出两形态（`yield` / `transmutes`）、实体来源四类、知识表的版本对账 |
| [`0006-trades.md`](0006-trades.md) | 交易族的规则形状、流浪商人单列假设、代码侧提取的完整性 |
| [`0007-transforms-and-tools.md`](0007-transforms-and-tools.md) | 方块变换的事实形状、反方向与命名约定、工具要求从组件推导 |
| [`0008-code-side-extraction.md`](0008-code-side-extraction.md) | 结构生成代码 、生物桶与流体桶、目录约定兜底与适配器约束 |
| [`0009-report-artifacts.md`](0009-report-artifacts.md) | 物品全集与可达率分母、关系图的内部表示与渲染分离 |
| [`0010-testing.md`](0010-testing.md) | 测试框架选型与版本过滤的生效时机 |
| [`0011-structure-layout-exports.md`](0011-structure-layout-exports.md) | 结构布局的四张白名单表、拼图关系进事实、台账三态 |
| [`0012-interaction-sources.md`](0012-interaction-sources.md) | 交互表的持有者与工具前置、类名到注册名的取法、无表交互落哪 |
| [`0013-spawn-tables.md`](0013-spawn-tables.md) | 刷怪权的四处来源归一、权重不折算、均匀数组不进表 |
| [`0014-datapack-overlay.md`](0014-datapack-overlay.md) | 数据包覆盖为何自己实现、合并语义、生效数据根与失败边界 |
| [`0015-mining-mechanics.md`](0015-mining-mechanics.md) | 挖掘时间机制为何进事实、硬度为何从源码取值、集合与复制包装的判据 |
