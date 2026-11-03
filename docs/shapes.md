# 数据形态指南

本文说明**在哪些位置找数据、按什么形状识别、什么情况下不能认**。它不记录某个版本有多少文件——规模随输入变化，由 `oa guide --label <label>` 从产物现场生成（写在 `output/<label>/guide.md`，不入版本库）。

适配一个新版本时，先读当前版本的指南取得实测结论，再对照本文的判据。两者的分工是：指南给出该版本的形态，本文给出识别判据与误判后果。

## 一条通则：按形状判，不按版本号

两版共用同一份探测与适配代码，没有 `version ==` 分支。目录名单复数、方言、世界生成归属、组件布局、交易层数，全部由输入自身报告。

如此约定的理由不在于代码整齐：按版本号分支的错误不会显现。新版本沿用旧名时行为正常，改名后该分支静默走空；而形状判据失效会立刻表现为归属覆盖率下降。

判据的共同要求是**按整块键集合判定，不按单个键**。只认白名单键、或要求「必须同时出现某两键」，都会把省略了可选键的合法写法成批漏掉，而漏项不会报错。

## 输入的第一手与派生

| 内容 | 性质 | 来源 |
|---|---|---|
| `server.jar` | 第一手 | 用户提供 |
| `java/` | 第一手，或由反编译源码仓按提交导出 | 用户提供，或 `manifest.toml` 的 `[source]` |
| `data/` | 派生 | 从 jar 内层解出，排除模板 |
| `version.json` | 派生 | 从 jar 内层解出 |
| `java.json` | 派生 | 导出时写的 marker |
| `assets/` | 可选 | 提供时逐文件登记台账，未提供不视为缺失 |

`java/` 是从服务端 jar 反编译得到的 Java 源码，既不是 JDK 源码，也不是游戏代码的原始源码（后者从未公开）。

派生内容不得手工放置。`data/` 与反编译源码树的 `resources/data` 除结构模板外逐一同名同路径，因此数据包不必从 `--server` 导出取得。

反编译源码仓的提交号由用户显式配置，程序不推导（[ADR 0014](adr/0014-commit-explicit-config.md)）。导出用 `git archive <提交>:<Java 源码根>`，不 checkout。Java 源码根由特征文件定位，不查候选目录表（[ADR 0013](adr/0013-source-tree-by-feature-file.md)）。

## 数据包目录归属

**位置**：数据包根下的各命名空间目录。

**判据**：取注册表条目名与目录内容的交集。用交集而不是「目录名等于注册表名」，使 `recipe`/`recipes`、`loot_table`/`loot_tables`、`structure`/`structures` 两种形态由同一份代码吸收。

**归属覆盖率**是判据的一部分：覆盖率过低说明该目录的内容大多不属于这个注册表，此时记 `unknown`，不强行归属。

**必须整棵排除的目录**：数据包里的实验包目录（形如 `datapacks/<包名>/`）不属于原版。其中有的包含真实内容（会与主数据包的同名条目互斥），误纳入会让同一职业等级同时出现两套互斥交易。

**探测到但形状不明确的目录**必须记进 `notes`，不得默认为不存在。`oa guide` 会将其列出，可作为新增适配器的候选来源。

## 标签

**位置**：`tags/<子目录>/`。

**判据**：标签子目录到注册表的归属靠两类锚点——运行期导出的 `registries.json`（只 dump 内置注册表）与数据包目录名（数据包驱动的注册表）。

**标签 ID 不含注册表子目录**：`tags/item/planks.json` 的标签 ID 是 `minecraft:planks`，`tags/villager_trade/armorer/level_1.json` 的是 `minecraft:armorer/level_1`。用「相对 tag 目录」计算，不切字符串。

**下潜策略**：顶层能锚定即停止。`tags/item/<名字>` 是标签名分层，`tags/worldgen/biome/<名字>` 是注册表分层——两者的目录深度含义不同，混用会导致锚定错误。

**空标签**按目录名直接锚定：hint 命中即归属，不要求有成员。

## 结构模板

**位置**：服务端 jar 内层的 `data/<ns>/<模板目录>/**/*.nbt`。

**第一手是 jar 内层的二进制模板**，不是反编译源码树的 `.snbt`。反编译源码树副本被打包过，`palette` 全为空串、`data[].state` 全为空、且没有顶层 `DataVersion`——它不构成合法的 datagen 输入，交给 `--server --input` 会在 `NbtUtils.snbtToStructure` 报 `Multiple entries with same key`（同一份 palette 里有多个空串条目）。

**模板目录靠形状定位**：内层 jar 里全为 `.nbt` 的 `data/<ns>/<子目录>` 即模板目录。不能按名字定位——两版的模板目录名与结构定义目录名互相错开，按名字定位会在两版上各错一处。

**转换方向**：二进制 `.nbt` 是展开形态（`palette` 是 compound 列表、`blocks[].state` 是整数索引），文本 `.snbt` 是打包形态（`palette` 是方块状态字符串列表、`data[].state` 是引用）。两者的 `palette` 字段键不同，按键是否存在判定，不按版本号。转换选项见 [数据生成器参数](datagen.md)。

**两个来源必须分开记**：

| 字段 | 来源 | 含义 |
|---|---|---|
| `blocks` | `data[].state` 经 palette 解析 | 该格子的方块类型 |
| `block_entity_ids` | `data[].nbt.id` | 该格子仅提供方块实体身份 |

合并成一个字段会让下游分不清两者。`nbt.id` 不是方块全量：普通方块的类型只能从 `data[].state` 取。`.snbt` 副本与 jar 副本的 `palette` 有值项对比、`nbt.id` 计数用 `tools/checks/check-template-nbt-id.py`。

方块名比对前要剥到第一个 `{` 或 `[`——取值带方块状态（`minecraft:grass_block{snowy:false}`），注册表里是裸名。

**模板 NBT 里的实体是某些实体的唯一数据包踪迹。** `entities[].id` 给出该格子里的实体；
村民、猫、马、铁傀儡、猪灵都属于这一类——它们不在任何生物群系的 `spawners` 里，
也不由配方产出。不读这个字段，这些实体在图上就是「零规则、不可获得」。

`entities[].id` 也可能不是实体（26.3 的 `minecraft:cushion` 是方块实体），
比对 `entity_type` 注册表后不通过的要留痕，不能静默跳过
（[ADR 0019](adr/0019-template-entities.md)）。

**反编译源码树里的同名模板仍逐文件登记**（`classified_skip` + 规则名），不静默忽略：它们存在于输入包里，只是不作为结构事实的来源。

## 世界生成

**位置**：数据包的 `worldgen/` 目录，或运行期导出的 `reports/worldgen/`。

**两侧来源互补**：一个版本通常只有一侧。因此双路对账只在两侧齐备时触发，单侧存在不构成缺失。

**对账判据是不对称的**：数据包是源文件全集，运行期只含注册成功的条目，所以「数据包多」正常；「运行期有而数据包没有」才是异常（注册成功但源文件缺失），记 `unresolved`。

**两侧子目录名不同**，比对前须归一：

| 数据包侧 | 运行期导出侧 |
|---|---|
| `feature` | `configured_feature` |
| `carver` | `configured_carver` |
| `structure` | `configured_structure_feature` |

数据包侧通常比运行期细得多，含运行期不导出的族，这进一步说明两边不是同一份内容。

**「放置了什么」与「冒出什么」是两个不同的问题**：

- `references` 记放置的方块、模板、特征、结构、标签，每条 `{slot, id}`。
- `spawns` 记结构 JSON 的 `spawn_overrides` 冒出的实体。

`slot` 只有 `block` / `entity` / `tag` / `feature` / `structure` / `template` 几种，其中 **`entity` 是兜底**——无法归类的引用都落在这里，它不代表「实体」。

方块引用有四种写法，判据见 [ADR 0005](adr/0005-worldgen-reference-shapes.md)：带属性表的状态对象、无属性表的状态对象、加权表项、裸 id 列表，另有标签引用。枚举验证用 `tools/probes/probe-worldgen-refs.py`。

`slot=tag` 不由适配器展开：标签名不是方块，展开属 IR 的语义。

**空 `spawn_overrides` 不等同于缺陷**：「结构内不额外刷怪」与「结构不存在」是两个不同的结论。结构整体的刷怪配置与刷怪笼配置也相互独立，后者是单独的事实种类。

## 运行期导出

**位置**：`net.minecraft.data.Main --reports` 的产物。

**必要性**：数据包里没有物品注册表，也没有默认组件。物品全集与组件只能从运行期导出取得。

**产物清单**：`registries.json`（全部内置注册表的条目 ID 与 protocol_id）、默认组件报告、`blocks.json`（方块属性）、`datapack.json`（数据包能力表）、命令与协议包。

**文件名是单数 `datapack.json`**，不是 wiki 上写的 `datapacks.json`。该报告从 1.21.2 起才有，早于此的版本没有。

**默认组件报告的布局随版本不同**（目录形态与单文件形态），探测记布局类型，下游按类型分派。

**数据包能力表的判据**：`registries.json` 只 dump `BuiltInRegistries`，数据包驱动的注册表不在其中；`datapack.json` 给的是「每个注册表能否被数据包增删/注入标签」，是地形包功能的权威依据，不靠约定。

## 物品全集与方块对应

**位置**：运行期导出的 `registries.json`，与输入包反编译源码树里的注册调用。

**分母必须是注册表全集**，不是「规则里出现过的 `item:` 节点」。后者会让没有任何规则的物品从报告里彻底消失——总数偏少而不易察觉（[ADR 0012](adr/0012-item-universe-from-registry.md)）。

**代码侧的字面量只能作交叉校验**，不能代替注册表：常量类里含无物品的方块 ID，`Items.java` 的字段数不等于物品数（集合字段展开后才是物品数）。

**物品与方块的对应不能按名字推断**。有一批物品的物品名与方块名不同（染料、种子、作物、线/绊线等），按名字配对会得到「能放置成不存在的方块」且真方块永远没有来源。对应关系只能从代码的注册调用取，且必须与注册表对账。

**注册名的取得优先级**：注册调用里的字符串字面量 > 常量类的显式名字 > 字段名小写。从常量名推出来的名字必须与注册表对账——拼写错误与词序不同都会得到不存在的名字，这类错误不报错，只在后续表现为「节点凭空缺失」。对账不过的事实剔除并记台账，不留悬空节点。

## 配方

**位置**：数据包的 `recipe`/`recipes` 目录。

**只有 `type` 的配方不是统一形态**。多数特殊配方仍带 `result` 与各自的原料字段，原料与产出可直接从 JSON 读；真正只有 `type` 的只是少数。按「特殊配方都是空壳」处理会丢掉整批原料关系。

**槽名随配方不同、不可枚举**，因此按通则收：除 `type`、`result`、`group`、`category` 外的每个顶层键都是原料槽；值是对象时（如 `shapes`）其每个成员各算一个原料。数据包里没有可收的槽时如实记 `partial`，不作推断。

**字段名相同不等于语义相同**：

- `pattern`：形状配方里是图案行数组，`smithing_trim` 里是 pattern 的字符串 ID。按值的形状区分，不按字段名。
- 产出字段：多数配方是 `result`，`brewing` 是 `output`，原料是 `input` + `reagent`。只按 `result` 实现会漏掉整个酿造族。
- `crafting_transmute` 的 `result` 允许写成 `{}`，表示产出由输入决定，是合法写法。

**`type` 与 `RecipeType` 是两个注册表**，不能混：`type` 取自序列化器注册表（决定怎么解析），`RecipeType` 粗粒度表示在哪做（决定工艺设备前置）。

**`ingredient` 与 `ingredients` 只差一个 s，语义相反**：

| 写法 | 含义 |
|---|---|
| `"ingredient": [A, B, C]` | **一个**槽位，**三选一**（熔炉单输入槽的 12 种金装备就是这样） |
| `"ingredients": [A, B, C]` | **三个**槽位，每个放一样（无序合成的铜块 + 蜜蜡） |
| `"ingredients": [[A, B], C]` | 两个槽位，第一个槽内二选一 |

整个 `ingredients` 数组交给解析器会被当成「一个槽内多选」，于是
`["copper_block", "honeycomb"]` 读成「铜块或蜜蜡之一」——上蜡铜块只需其中任一样。
这类错误不报错、只让可达性变宽：1.18.2 的 `waxed_copper_block` 因此从
FALSE 翻成 TRUE（蜜蜡本身不可得，本该整条不通）。

判据是**数组的层级**，不是字段名的复数：逐元素解析，元素本身是数组时才算多选。
IR 的 `body` 只有 AND，所以槽位内多选要在编译期展开成多条同 head 规则
（26.3 共 295 条配方有多选槽，展开后配方规则 1787 → 3449，最大笛卡尔积 16）。

## 战利品表

**位置**：数据包的 `loot_table`/`loot_tables` 目录。目录名即触发语义。

**方言按每个文件自身的形状判定**，不依赖全局主方言。同一版本内可以并存两种写法。

**格式要点**（沿用旧写法实现会静默漏扫）：

- 函数数组的键是 `modifier`，值可以是对象或数组。对象内的类型键是 `type`，不是 `function`。
- 条件是单数字段 `condition`，可写成对象或字符串引用。对象内的类型键同样是 `type`，不是 `condition`。
- 条件可以被抽成独立注册表（`predicate`），`condition` 里写的是对该注册表条目的引用。

**条目类型**共 9 种：`empty`、`item`、`loot_table`、`dynamic`、`tag`、`slots`、`alternatives`、`sequence`、`group`。`dynamic` 条目必须显式登记，不能静默跳过。

**借用他人的表**：有一类方块自己没有表，而在注册时挂上另一个方块的表，数据包里看不到这层关系。判据是注册调用里的借用写法（`dropsLike` / `wallVariant` 一类）。这类产出的表 id 是按方块名推的，必须与 `loot_table` 事实比对，不存在的记 `failed`。

**「箱子表属于哪个结构」必须从模板与 `template_pool` 处理器推**，无法从战利品表侧反推。

**工具要求不在战利品表里。** 「绿宝石矿要铁镐」是方块属性，不是表里的一条
条件。能从表侧读到的只有「具体工具或附魔」（`can_shear`、`can_silk_touch`
这类谓词）。等级要求必须从物品的 `minecraft:tool` 组件与
`incorrect_for_*_tool` 标签推，判据见[默认组件](#默认组件)与
[ADR 0016](adr/0016-tool-requirement-from-components.md)。

**`any_of` 里的硬条件是 OR，不能当成无法判定的组合器丢掉。** 树叶与蜘蛛网的
掉落物条目就是 `any_of(can_shear, can_silk_touch)`。丢掉它会让这些方块看起来
「随便挖就掉」，且可达性结论不变，所以从状态数上看不出错误。

**`all_of` 与 `inverted` 不能按同样方式展开。** 前者的 terms 掺了概率与软条件，
后者是否定；把其中任何一项升成硬前置都会凭空多出工序。

**没有代码入口的表按目录约定挂产出者，有代码入口的必须走事实。**
`blocks/` 与 `entities/` 由路径推出方块/实体（名字须在注册表里）；其余首段
（`chests/` `archaeology/` `pots/` `gameplay/` …）在
`knowledge/maps/mechanism/table_providers.json` 里登记一条假设节点。

目录约定是**兜底**，不是分类依据：同一首段下可以混着互不相干的机制。
`gameplay/` 就同时有钓鱼、猪灵以物易物、袭击后村民送礼、嗅探兽挖掘与生物被动
产出。付款物在代码里写明的那几条必须由 idiom 出事实——取值顺序是事实优先，
`piglin_bartering` 因此不落在目录假设上，见
[ADR 0021](adr/0021-piglin-barter-from-code.md)。

判据：付款物是源码里的常量（`BARTERING_ITEM = Items.GOLD_INGOT`）就走代码抽取；
付款物随场景变化又无常量（钓鱼的「鱼竿」、晨礼的「村庄」）才走目录假设。

## 交易

**位置**：数据包的 `trade_set` / 交易标签 / `villager_trade` 三层目录，或输入包反编译源码树里的交易表。

**三层结构**：交易组（`trade_set`，用标签引用单条交易）→ 标签（聚合）→ 单交易（`gives`/`wants`）。并非每个版本三层都在数据包里；整张交易表硬编码在代码里的版本，按代码侧惯用法处理。

**形状判定有顺序要求**：交易组带 `random_sequence`，与战利品表同键。按形状识别目录时，交易组的判定必须排在战利品表之前，否则整个交易组目录会被当成战利品表。

**交易的字段顺序决定方向**：构造器参数里第一个是买家付出的物品。仅凭类名判断方向会得到完全相反的结论。

**交易标签的 ID 同样不含注册表子目录**。

**`profession` 决定前提，不由等级决定**：目录第一段就是职业（`villager_trade/<profession>/…`）。
`wandering_trader` 单独用 `assume:wandering_trader`，其余职业共用 `assume:villager_trade`——
两者前提不同（流浪商人随机生成、不补货、不依赖村庄），见
[ADR 0017](adr/0017-wandering-trader-assumption.md)。等级缺席（`level = null`）是目录
结构的副产品，不能当作商人类别的判据。

**一笔交易可以要不止一样东西。** `wants` 之外还有 `additional_wants`（数据包形态），
代码侧则是 `MerchantOffer(costA, costB, result, …)` 的两个支付位。附魔书要绿宝石 +
书、藏宝图要绿宝石 + 指南针。只取第一个支付物会得到「绿宝石换附魔书」，把书这个
前提抹掉（[ADR 0018](adr/0018-code-side-trade-extraction.md)）。

**流浪商人的交易表与职业村民不在一处。** 1.18.x 是独立的
`VillagerTrades.WANDERING_TRADER_TRADES`（`toIntMap(ImmutableMap.of(1, new ItemListing[]{…}, 2, …))`），
不在按职业注册的 `TRADES` 里。只扫 `hashMap.put(VillagerProfession.X, …)` 会整批漏掉。

**交易类的实参语义按 `MerchantOffer` 的参数顺序定，有重载的要按实参数分派。**
`ItemsAndEmeraldsToItems` 的 6 参重载把 `emeraldCost` 折叠成 1，`to/toCount` 因此在
arg2/arg3；7 参重载显式给出，整体后移一位。判据是实参个数，不是版本号。

**产出物可以带随机属性而 id 不变。** `given_item_modifier`（数据包）与
`EnchantedItemForEmeralds` / `EnchantBookForEmeralds` / `TippedArrowForItemsAndEmeralds` /
`DyedArmorForEmeralds`（代码）都属于这一类：附魔、药水、染料是随机的，物品 id 不变。
不要拆成 `enchant:*` 节点——那会把「随机附魔」说成「确定附魔」。

## 默认组件

**位置**：运行期导出的默认组件报告。

**「不具有」的表达方式是键缺席**：每个物品只列出它实际具有的组件。不能把 `!X: {}` 读成「具有 X 且值为空对象」，否则变体维度推导会多出假维度。前缀写法在某些版本不出现，适配器仍须支持——判据是键名前缀，不是版本号（[ADR 0001](adr/0001-components-fact-kind.md)）。

**组件键可判语义**：食物、工具与武器、装备、耐久、方块转换、容器、打蜡态各有对应的组件键。每个物品的默认组件由运行期导出直接给出，无需解析反编译源码。

**没有该报告的版本**记族级不可用，不用空集合代替「没有组件」。

**工具能力直接从 `minecraft:tool` 组件读**：规则里的 `blocks` 是标签引用，
`correct_for_drops` 为假的是「不能挖」，为真的是「能挖」。等级没有数字，
`incorrect_for_stone_tool` 一类标签用嵌套表达递增关系。因此不建等级表，
也不建「材质 → 物品名」清单（[ADR 0016](adr/0016-tool-requirement-from-components.md)）。

**「必须用正确工具才掉」这个标记没有数据源。** `blocks.json` 报告只有状态，
组件只有工具自己的能力。可用的近似判据是「方块是否在 `incorrect_for_*` 里」：
在里面就需要一档够用的工具，不在里面就可能徒手。这个判据会少报「石头需要
任意镐」，但不会误报。

## 方块转换

**位置**：数据包的 `block_transformer` 注册表（数组而非单对象），或代码里的静态映射表。同一事实种类，`transformer_kind` 区分形态。

**规则内部只有 `if_true` 与 `then`**，`if_true` 有三种形态：`matching_blocks`、`all_of`+`predicates`、`matching_block_tag`。字段全集用 `tools/probes/probe-block-transformer.py` 枚举。

**`offset` 决定这个判据是被转换的方块还是环境前提**：带 `offset` 表示「该位置的方块是空」，属环境前提；无 `offset` 才是源方块。把 `air` 当源方块会让「泥土 → 耕地」变成「空气 → 耕地」，路径必然中断（[ADR 0002](adr/0002-block-transform-fact-kind.md)）。

**逆变换**：有的表声明为另一张表的 inverse，方向须翻转。

**由构造器参数驱动的表不抽取**：形态是 `表.put(参数, this)`，参数是变量而非字面量，按「不做构造器推断」的边界处理，逐表记台账。

## 代码侧的获取关系

**位置**：输入包的反编译源码树。

**锚点必须是调用形态，不能是类名**。同一个类里既有获取关系也有无关的闭包引用，按类名匹配会大量误收。例如裸类名命中的绝大多数是 `import`，没有一处表达获取关系。

**留痕分四层，每层都不能静默**：

| 层次 | 含义 | 落在哪 |
|---|---|---|
| `extracted` | 已产出事实 | 事实的 `prov` |
| `candidate` | 疑似有机制，尚未确认 | 台账逐文件登记 |
| `no_anchor` | 找不到锚点 | 只记规则名与计数 |
| `excluded` | 判定不属于获取关系 | 只记规则名与计数 |

**只取分支体**：分支外的前置代码若被纳入扫描范围，会使相邻分支的物品归属错误。扫描范围须截至该语句的配对右括号，不能截至区域末尾——否则同一段代码会被后续每个兄弟节点重复计入。

**全大写常量直接小写**，不做驼峰转换：一律驼峰会得到逐字母下划线的名字。

**各族的判据**（形态、边界、何时不留痕）见对应的 ADR：[结构生成代码里的物品](adr/0004-elytra-and-buckets.md)、[交易族](adr/0007-trades-family.md)、[绑定与例外表](adr/0008-bindings-and-exceptions.md)、[实体行为族](adr/0010-entity-behaviour.md)、[猪灵以物易物](adr/0021-piglin-barter-from-code.md)。

## 事实种类与族级不可用

**族级不可用**用 `FactStore.mark_unavailable` 登记，**不写台账**——写台账会让覆盖率分母虚高。缺一个报告、缺一个目录都属于这一类，而不是「产出 0 条」。

**归因按类统计**用 `tools/gaps/gap-reasons.py`：`unobtainable` 与 `no_rule` 的分界靠例外表，其余归因由求解结果直接给出。

**扫描不到的东西必须显式登记**：只有 `type` 的配方、`dynamic` 战利品条目、数据包内无引用点的代码绑定，一律留痕。

**不做的几类**是边界决定，不是待办：构造器参数推断（参数是枚举不是被转换的方块）、代码里的任意 `setBlock`（上下文差异大，未逐条核实）、未核实的交互转换。它们的判据在 ADR 里，新增时先确认是否落在边界外。

**枚举型字段的全集来自注册表**，可机器导出，因此覆盖率闸门不需要人工维护白名单。计数须先提取注册名字面量再去重：注册方法体内的那一次也会被计入，类文件数也不等于注册名数。
