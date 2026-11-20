# 数据形态指南

本文说明**在哪些位置找数据、按什么形状识别、什么情况下不能认**。它不记录某个版本有多少文件——规模随输入变化，由 `ra guide --label <label>` 从产物现场生成（写在 `output/<label>/guide.md`，不入版本库）。

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
| `datapacks/` | 第一手，可选 | 用户提供；每项是含 `pack.mcmeta` 的目录或 `.zip` |
| `data/` | 派生 | 从 jar 内层解出，排除模板 |
| `version.json` | 派生 | 从 jar 内层解出 |
| `pack.mcmeta` | 派生 | 从 jar 内层解出；内层通常没有该文件，缺失不算失败 |
| `datapack-merged/` | 派生 | 原版数据与 `datapacks/` 的覆盖合并结果 |
| `java.json` | 派生 | 导出时写的 marker |
| `assets/` | 可选 | 提供时逐文件登记台账，未提供不视为缺失 |

`java/` 是从服务端 jar 反编译得到的 Java 源码，既不是 JDK 源码，也不是游戏代码的原始源码（后者从未公开）。

派生内容不得手工放置。`data/` 与反编译源码树的 `resources/data` 除结构模板外逐一同名同路径，因此数据包不必从 `--server` 导出取得。

反编译源码仓的提交号由用户显式配置，程序不推导（[ADR 0001](adr/0001-inputs-and-source-export.md)）。导出用 `git archive <提交>:<Java 源码根>`，不 checkout。Java 源码根由特征文件定位，不查候选目录表。

## 数据包覆盖

**位置**：`inputs/<label>/datapacks/` 是外来数据包，`inputs/<label>/datapack-merged/` 是合并结果。

**每项的形状**：带 `pack.mcmeta` 的目录，或根下含 `pack.mcmeta` 的 `.zip`。既不是目录也不是 `.zip` 的条目一律报错。

**`pack.mcmeta` 的段**：

| 段 | 用途 |
|---|---|
| `pack` | 格式范围：新式 `min_format` / `max_format`（可带 minor），旧式 `pack_format` / `supported_formats` |
| `overlays` | `entries[].directory` 指向包内子目录，带自己的格式范围；按当前格式筛出适用的层 |
| `filter` | `block[]` 的 `namespace` / `path` 正则，屏蔽更低优先级的包 |

**顺序**：版本段的 `datapacks = [...]` 按低到高列出。目录里有而未列出的包报错，列表里有而不存在的包也报错——两种都是输入与配置不一致。未配置列表时按名称升序加载并记 `notes`。

**包内优先级**：包根最高，其后是适用 overlay 的逆序（后列出者优先）。因此包根的同名定义不会被某个版本的补丁盖掉，而两个 overlay 冲突时以后者为准。

**合并结果的结构**：`data/` 即生效数据根，`merge-log.jsonl` 逐行记录覆盖与标签合并，`.datapack-merge.json` 是失效判据与包摘要。没有数据包时不生成该目录，生效数据根就是 `data/`。

**生效数据根只有一个读入口**：探测写入 `Profile.data_root`，适配器一律读它。目录归属、方言、标签归属都相对它计算，因此合并后看到的目录形状就是游戏看到的那份。

覆盖与合并的语义、失败与留痕的分界，见 [ADR 0014](adr/0014-datapack-overlay.md)。

**数据包内的 `assets/` 不入合并结果**：数据包合并只作用于 `data/` 侧。这些文件在台账里逐条登记为「非 data/ 内容」。

**内置实验包仍整棵排除**：`data/<ns>/datapacks/` 下的包按 Feature Flag 启用，默认关闭；覆盖功能不改变这条判据。

## 数据包目录归属

**位置**：数据包根下的各命名空间目录。

**判据**：取注册表条目名与目录内容的交集。用交集而不是「目录名等于注册表名」，使 `recipe`/`recipes`、`loot_table`/`loot_tables`、`structure`/`structures` 两种形态由同一份代码吸收。

**归属覆盖率**是判据的一部分：覆盖率过低说明该目录的内容大多不属于这个注册表，此时记 `unknown`，不强行归属。

**必须整棵排除的目录**：数据包里的实验包目录（形如 `datapacks/<包名>/`）不属于原版。其中有的包含真实内容（会与主数据包的同名条目互斥），误纳入会让同一职业等级同时出现两套互斥交易。

外来数据包不放这里，它们是 `inputs/<label>/datapacks/` 的第一手输入，按覆盖规则合并（见下节）。

**探测到但形状不明确的目录**必须记进 `notes`，不得默认为不存在。`ra guide` 会将其列出，可作为新增适配器的候选来源。

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

**模板 ID 是模板根之后的全部路径**：`data/<ns>/<模板目录>/x/y.snbt` → `x/y`。模板自身可以含与根目录同名的子目录（`ancient_city/structures/barracks`），按目录名再切一次会把 ID 截成裸名，join 不上任何引用。

**容器身份与方块格数分开记**：

| 字段 | 来源 | 含义 |
|---|---|---|
| `containers` | `data[].nbt` 的 `LootTable`，或空的 `Items` | 战利品容器坐标、方块实体类型、战利品表（可缺） |
| `loot_tables` | 同上，只取有表的 | 表已知的容器子集 |
| `block_counts` | `data[].state` 计数 | 每个状态串在模板里的格数 |

容器判据是「能挂表 + 还没有内容」：`LootTable` 引用，或 `Items` 为空且方块实体属于实现 `RandomizableContainer` 的那批（箱子、木桶、漏斗、投掷器、潜影盒、饰纹陶罐、合成器）。`Items` 非空的格子不算战利品容器——内容已经确定，逐件记在 `item_refs` 里；篝火、熔炉、酿造台也带 `Items` 槽，却从不承载表，混进来会让「每个结构几个箱子」偏大。

**`containers[].table` 可以为 null**：有些结构的箱子在模板里，表却由生成代码在运行时挂上（船骸、末地城、庄园），模板 NBT 里没有 `LootTable` 一项。只记有表的容器会让这些结构在导出表里整族缺席。`container_count` 是容器格数，`loot_tables` 保留为有表的子集，既有消费方按「一行必带表」读取不受影响。

`blocks` 是去重后的状态串列表，`block_count` 是总格数，两者都无法回答「这个方块在模板里有几个」。

方块名比对前要剥到第一个 `{` 或 `[`——取值带方块状态（`minecraft:grass_block{snowy:false}`），注册表里是裸名。

**模板 NBT 里的实体是某些实体的唯一数据包踪迹。** `entities[].id` 给出该格子里的实体；
村民、猫、马、铁傀儡、猪灵都属于这一类——它们不在任何生物群系的 `spawners` 里，
也不由配方产出。不读这个字段，这些实体在图上就是「零规则、不可获得」。

`entities[].id` 也可能不是实体（26.3 的 `minecraft:cushion` 是方块实体），
比对 `entity_type` 注册表后不通过的要留痕，不能静默跳过
（[ADR 0004](adr/0004-structure-and-template-bindings.md)）。

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
- `spawns` 记刷怪条目：结构来自 `spawn_overrides`，群系来自自然刷怪表。每条 `{category, entity, weight, count_min, count_max}`。

`slot` 只有 `block` / `entity` / `tag` / `feature` / `structure` / `template` 几种，其中 **`entity` 是兜底**——无法归类的引用都落在这里，它不代表「实体」。

方块引用有四种写法，判据见 [ADR 0003](adr/0003-worldgen-and-references.md)：带属性表的状态对象、无属性表的状态对象、加权表项、裸 id 列表，另有标签引用。枚举验证用 `tools/probes/probe-worldgen-refs.py`。

`slot=tag` 不由适配器展开：标签名不是方块，展开属 IR 的语义。

**拼图结构的内部布局分两处**：结构 JSON 的 `start_pool` 与 `size` 给起始池与拼装深度上限，`template_pool` 的 `elements` 给候选模板与权重。池内 `list_pool_element` 的嵌套成员摊平后带 `nested`——它们的权重与顶层不是同一分母，不得混算权重和。

池还能经模板的拼图方块（`jigsaw_pools`）继续向下展开，所以结构到模板是传递闭包，不是一跳。

**处理器可以把方块换成带战利品表的方块**：`processor_list` 里的 `block_entity_modifier: {type: append_loot, loot_table: ...}` 配 `output_state`（可疑沙 / 砾石），`capped.limit` 限每片段最多替换几处。这类容器不在模板 NBT 里，模板侧看不到；池元素的 `processors` 记录该模板应用了哪些处理器。

**方块引用来自 JSON 是常态，不是全部。** 有一类特征只在 JSON 里写参数，方块名落在实现类里：
`feature/sculk_patch_deep_dark.json` 只有电量与扩散次数，`Blocks.SCULK` 在
`SculkVeinBlock#attemptPlaceSculk`。这类由
`knowledge/maps/mechanism/worldgen_code_blocks.json` 补，编译期以「该版本有特征引用这个类型」
为门控，见 [ADR 0003](adr/0003-worldgen-and-references.md)。

门控要匹配 `references` 里的 id，不是特征 JSON 的顶层 `type`：顶层往往只是容器
（`sequence`），真正的特征类型是 `features` 数组里的元素。

**结构容器也可能只存在于生成代码里。** 下界要塞、要塞、废弃矿井没有模板，容器与表都在拼装器代码里；船骸、末地城、庄园的模板有箱子但没有 `LootTable`。这类绑定记成 `structure_container` 事实，三跳全部取自代码：

1. `StructureType.register("<id>", <类>.CODEC)`（26.x）或 `StructureFeature.register("<id>", new <类>(...))`（1.18.2）
2. 结构类正文里引用、且在索引里真实存在的 `*Pieces` / `*Piece` 类
3. 拼装器正文里 `BuiltInLootTables.<常量>` 所在语句

容器形态按语句里的调用名判：`createChest` → `chest`，`createDispenser` → `dispenser`，`Map.of("标记", 常量)` → `marker`（另给 `marker` 字段），`archyRuleProcessor` / `AppendLoot` → `processor`，`setLootTable` / `setBlockEntityLootTable` → 语句含 `chest` 时 `chest` 否则 `block_entity`。判定前先抹掉常量文本，否则 `IGLOO_CHEST` 这类名字会反过来影响形态判断。

**空 `spawn_overrides` 不等同于缺陷**：「结构内不额外刷怪」与「结构不存在」是两个不同的结论。结构整体的刷怪配置与刷怪笼配置也相互独立，后者是单独的事实种类。

**群系刷怪表两版位置不同，条目字段也不同**：

| 版本 | 位置 | 条目 |
|---|---|---|
| 新版 | `attributes["minecraft:gameplay/natural_mob_spawns"].argument.spawns_by_category` | `type` / `weight` / `count`（整数或 `{min_inclusive, max_inclusive}`） |
| 旧版 | 顶层 `spawners` | `type` / `weight` / `minCount` / `maxCount` |

结构与群系的刷怪条目在事实里归一成同一组字段，数量拆成 `count_min` / `count_max`。
`weight` 是同一持有者、同一类别内的**相对**权重，折算概率要由消费方分组求和，适配器不做。
`spawn_costs`（同种生物刷多了变贵的能量预算）原样保留，键是实体 id。判据与取舍见 [ADR 0013](adr/0013-spawn-tables.md)。

**模板里的刷怪笼方块实体**由 `SpawnPotentials` / `SpawnData` 两个键识别，不按方块名（这个方块改过名）。两者并存时只取 `SpawnPotentials`：`SpawnData` 只是其中一项的初值，重复记会让同一实体出现两次。

**试炼刷怪笼配置的字段**（`data/<ns>/trial_spawner/**`）：

| 字段 | 含义 | 事实里的处理 |
|---|---|---|
| `spawn_potentials` | 刷什么 + 相对权重 | `entities[{id, weight, equipment}]` |
| `loot_tables_to_eject` | 打完弹什么表 + 相对权重 | `eject_tables`，不祥钥匙就在这张表里 |
| `simultaneous_mobs*` / `total_mobs*` / `ticks_between_spawn` | 难度参数 | `difficulty` 原值，不折算 |

`normal` 与 `ominous` 两套配置同形，靠路径末段区分；后者只在玩家带不祥之兆时启用。

**袭击波次不在数据包里**：`Raid$RaiderType` 枚举给出「实体 → 每波基础数量」的数组，下标即波次（`groupNumber = groupsSpawned + 1`，第 0 位不被读取）。波数由难度的 `numGroups` 决定（简单 3、普通 5、困难 7），奖励波取数组的 `[numGroups]` 项。判据见 [ADR 0013](adr/0013-spawn-tables.md#五波次是独立的一维不能折算成总数)。

## 运行期导出

**位置**：`net.minecraft.data.Main --reports` 的产物。

**必要性**：数据包里没有物品注册表，也没有默认组件。物品全集与组件只能从运行期导出取得。

**产物清单**：`registries.json`（全部内置注册表的条目 ID 与 protocol_id）、默认组件报告、`blocks.json`（方块属性）、`datapack.json`（数据包能力表）、命令与协议包。

**文件名是单数 `datapack.json`**，不是 wiki 上写的 `datapacks.json`。该报告从 1.21.2 起才有，早于此的版本没有。

**默认组件报告的布局随版本不同**（目录形态与单文件形态），探测记布局类型，下游按类型分派。

**数据包能力表的判据**：`registries.json` 只 dump `BuiltInRegistries`，数据包驱动的注册表不在其中；`datapack.json` 给的是「每个注册表能否被数据包增删/注入标签」，是地形包功能的权威依据，不靠约定。

## 物品全集与方块对应

**位置**：运行期导出的 `registries.json`，与输入包反编译源码树里的注册调用。

**分母必须是注册表全集**，不是「规则里出现过的 `item:` 节点」。后者会让没有任何规则的物品从报告里彻底消失——总数偏少而不易察觉（[ADR 0009](adr/0009-report-artifacts.md)）。

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

**函数可以改变物品身份。** `exploration_map` 把空地图改写成带目的地数据的地图：
新版数据里 `name` 已经写成具体地图（`abandoned_camp_map` 一类），旧版写的是
`map`、产物才是 `filled_map`。带这个函数的条目补两个字段：

| 字段 | 含义 |
|---|---|
| `product_id` | **修饰后**的物品身份。旧版 `map` → `filled_map`；新版与 `name` 相同 |
| `map_destination` / `map_decoration` / `map_zoom` | 函数参数原样保留，供按目的地展开 |
| `map_structures` | `destination` 展开后的结构 id 列表：`#minecraft:on_abandoned_camp_bamboo_jungle` → `minecraft:abandoned_camp_bamboo_jungle` |

`name` 保持数据原样，不做改写。下游按 `product_id` 判身份，不必自己实现一遍
`exploration_map` 的语义（[ADR 0002](adr/0002-fact-and-link-kinds.md)）。

`map_structures` 默认按结构注册表的 `tag` 事实展开（嵌套标签逐层进去），
`destination` 直接写结构名时就是它自己，展开不到时为空列表。
结构注册表的两个名字都要认：`worldgen/structure` 与旧版的 `worldgen/configured_structure_feature`。

旧版数据**不写** `destination`：它的值等于代码默认值时序列化会省略。默认值从源码取
（`ExplorationMapFunction.DEFAULT_FEATURE = ConfiguredStructureTags.ON_TREASURE_MAPS`），
补出来的条目带 `map_destination_default: true`——与数据里写明的分开，两者可信度不同。
源码里也找不到默认值、或默认标签不在 `tag` 事实里时不补，只把条数记进 `facts/summary.json`
的 `loot_map_destination_default_unresolved`。

**摊平不等于丢语义。** 逐条目一行时仍要带两样东西：

| 字段 | 何时出现 | 读法 |
|---|---|---|
| `weight` / `quality` | 原数据写了才出 | `weight ?? 1`、`quality ?? 0`；缺省与显式 1 是不同事实 |
| `group_id` / `group_kind` | 容器行给自己，子条目给所在分组 | 容器行 `children > 0`；`group_kind` 取 `alternatives` / `sequence` / `group` |

分组 id 用路径（`p<池>e<下标>`，子层缀 `c<下标>`），不用计数器：计数器在同一张表里重复运行不稳定，跨版本 diff 对不上。只留 `children` 计数时，「二选一」与「全都给」在产物上无法区分，期望值无从谈起。

**借用他人的表**：有一类方块自己没有表，而在注册时挂上另一个方块的表，数据包里看不到这层关系。判据是注册调用里的借用写法（`dropsLike` / `wallVariant` 一类）。这类产出的表 id 是按方块名推的，必须与 `loot_table` 事实比对，不存在的记 `failed`。

**「箱子表属于哪个结构」必须从模板与 `template_pool` 处理器推**，无法从战利品表侧反推。

**工具要求不在战利品表里。** 「绿宝石矿要铁镐」是方块属性，不是表里的一条
条件。能从表侧读到的只有「具体工具或附魔」（`can_shear`、`can_silk_touch`
这类谓词）。等级要求必须从物品的 `minecraft:tool` 组件与
`incorrect_for_*_tool` 标签推，判据见[默认组件](#默认组件)与
[ADR 0007](adr/0007-transforms-and-tools.md)。

**`any_of` 里的硬条件是 OR，不能当成无法判定的组合器丢掉。** 树叶与蜘蛛网的
掉落物条目就是 `any_of(can_shear, can_silk_touch)`。丢掉它会让这些方块看起来
「随便挖就掉」，且可达性结论不变，所以从状态数上看不出错误。

**`all_of` 与 `inverted` 不能按同样方式展开。** 前者的 terms 掺了概率与软条件，
后者是否定；把其中任何一项升成硬前置都会凭空多出工序。

**没有代码入口的表按目录约定挂产出者，有代码入口的必须走事实。**
`blocks/` 与 `entities/` 由路径推出方块/实体（名字须在注册表里）；其余首段
（`chests/` `archaeology/` `pots/` `gameplay/` …）在
`knowledge/maps/mechanism/table_providers.json` 里登记一条假设节点。

**顶层 `type` 是触发语义，不是持有者。** `block_interact`、`entity_interact`、
`shearing` 三类由交互触发；「对什么用、要什么工具」写在
`dropFrom*InteractLootTable` 的调用点所在的类里。按表名首段猜目标会错：
`harvest/cave_vine` 的目标方块是 `cave_vines`。判据与反例见
[ADR 0012](adr/0012-interaction-sources.md)。

目录约定是**兜底**，不是分类依据：同一首段下可以混着互不相干的机制。
`gameplay/` 就同时有钓鱼、猪灵以物易物、袭击后村民送礼、嗅探兽挖掘与生物被动
产出。付款物在代码里写明的那几条必须由 idiom 出事实——取值顺序是事实优先，
`piglin_bartering` 因此不落在目录假设上，见
[ADR 0008](adr/0008-code-side-extraction.md)。

判据：付款物是源码里的常量（`BARTERING_ITEM = Items.GOLD_INGOT`）就走代码抽取；
付款物随场景变化又无常量（钓鱼的「鱼竿」、晨礼的「村庄」）才走目录假设。

## 交易

**位置**：数据包的 `trade_set` / 交易标签 / `villager_trade` 三层目录，或输入包反编译源码树里的交易表。

**三层结构**：交易组（`trade_set`，用标签引用单条交易）→ 标签（聚合）→ 单交易（`gives`/`wants`）。并非每个版本三层都在数据包里；整张交易表硬编码在代码里的版本，按代码侧惯用法处理。

**形状判定有顺序要求**：交易组带 `random_sequence`，与战利品表同键。按形状识别目录时，交易组的判定必须排在战利品表之前，否则整个交易组目录会被当成战利品表。

**交易的字段顺序决定方向**：构造器参数里第一个是买家付出的物品。仅凭类名判断方向会得到完全相反的结论。

**交易标签的 ID 同样不含注册表子目录**。

**`profession` 决定前提，不由等级决定**：目录第一段是职业（`villager_trade/<profession>/…`），
但**不总是**——首段不在 `trade_set/` 子目录集合里的是**共用条目目录**（`smith/` 的
三条交易被盔甲匠、工具匠、武器匠通过 `#minecraft:common_smith/level_N` 共用），
记 `profession = null` + `shared_group`（分组名从标签目录读，不按 `common_` + 首段拼）。
真实归属另由 `applies_to` 给出：从 `trade_set` 的 `trades` 标签递归展开 `#` 嵌套，
反向得到「条目 → [(职业, 等级)]」，一条可属于多个职业。
`wandering_trader` 单独用 `assume:wandering_trader`，其余职业共用 `assume:villager_trade`——
两者前提不同（流浪商人随机生成、不补货、不依赖村庄），见
[ADR 0006](adr/0006-trades.md)。等级缺席（`level = null`）是目录
结构的副产品，不能当作商人类别的判据。

**一笔交易可以要不止一样东西。** `wants` 之外还有 `additional_wants`（数据包形态），
代码侧则是 `MerchantOffer(costA, costB, result, …)` 的两个支付位。附魔书要绿宝石 +
书、藏宝图要绿宝石 + 指南针。只取第一个支付物会得到「绿宝石换附魔书」，把书这个
前提抹掉（[ADR 0006](adr/0006-trades.md)）。

**事实里的 `wants` 一律是数组**，与 `additional_wants` 同形。数据包有时把单个
支付物写成对象 `{count, id}`，照原样放进事实会让下游写两条分支；统一成
`[{count, id}]` 之后，两种写法只有一个读法。

**对价不一定在数据里。** 附魔书报价的 `wants.count` 写的是 `0`，真实价格由
`enchant_randomly` 选中附魔的等级决定：

```
ADDITIONAL_TRADE_COST = 2 + random(5 + 10*level) + 3*level     # EnchantRandomlyFunction#enchantItem
价格 = clamp(wants.count + 附加, 0, 支付物的 max_stack_size)      # VillagerTrade#getOffer
宝藏附魔再 ×2（1.18.2 的 EnchantBookForEmeralds 另有同样一条）
```

这类报价把 `count` 写成 `{min, max}`，并附 `price_model`（公式、等级区间、
是否翻倍、夹取上限、依据）。等级区间从 `options` 指向的附魔标签展开、
`max_level` 读附魔定义；标签没有事实或定义缺 `max_level` 时不猜，
记 `missing` 并把这一条标 `partial`。

**交易组不按等级划分时 `level` 缺席**：流浪商人的 `buying` / `common` / `uncommon`
三个交易组没有等级段。事实标 `partial` 并写 `missing`，台账同步标 `partial`——
下游按（职业, 等级）索引时能识别落空，而不是拿到一个无法区分的空键。

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

**交易参数两版形态不同，事实里同名。** 数据包是字段（`xp` / `max_uses` /
`reputation_discount` / `price_multiplier`，`xp` 可缺）；代码是构造器实参，字段名是
`villagerXp` / `maxUses` / `priceMultiplier`。代码侧判据是**构造器体里的字段赋值**
（`this.villagerXp = n4;`），不是实参位置——反编译后形参名是 `n`/`n2`/`n3`，
且同类不同重载的位置不同；只做委托的重载沿位置回溯（`ItemsForEmeralds` 的 4 参
版本把 `maxUses` 固定成 12）。取不到的实参记 `unresolved_<字段>`，不猜值。

**缺字段按 codec 默认补上并标记**：`VillagerTrade.CODEC` 里 `max_uses` 默认 4、
`xp` 默认 1、`reputation_discount` 默认 0.0。补齐的键记进 `meta.defaults`——
「显式写了 1」与「缺省得到 1」是不同事实，不能因为值相同就合并。
见 [ADR 0006](adr/0006-trades.md#四交易参数按构造器体回取)。

## 默认组件

**位置**：运行期导出的默认组件报告。

**「不具有」的表达方式是键缺席**：每个物品只列出它实际具有的组件。不能把 `!X: {}` 读成「具有 X 且值为空对象」，否则变体维度推导会多出假维度。前缀写法在某些版本不出现，适配器仍须支持——判据是键名前缀，不是版本号（[ADR 0002](adr/0002-fact-and-link-kinds.md)）。

**组件键可判语义**：食物、工具与武器、装备、耐久、方块转换、容器、打蜡态各有对应的组件键。每个物品的默认组件由运行期导出直接给出，无需解析反编译源码。

**没有该报告的版本**记族级不可用，不用空集合代替「没有组件」。

**工具能力直接从 `minecraft:tool` 组件读**：规则里的 `blocks` 是标签引用，
`correct_for_drops` 为假的是「不能挖」，为真的是「能挖」。等级没有数字，
`incorrect_for_stone_tool` 一类标签用嵌套表达递增关系。因此不建等级表，
也不建「材质 → 物品名」清单（[ADR 0007](adr/0007-transforms-and-tools.md)）。

**「必须用正确工具才掉」这个标记没有数据源。** `blocks.json` 报告只有状态，
组件只有工具自己的能力。可用的近似判据是「方块是否在 `incorrect_for_*` 里」：
在里面就需要一档够用的工具，不在里面就可能徒手。这个判据会少报「石头需要
任意镐」，但不会误报。

## 方块转换

**位置**：数据包的 `block_transformer` 注册表（数组而非单对象），或代码里的静态映射表。同一事实种类，`transformer_kind` 区分形态。

**规则内部只有 `if_true` 与 `then`**，`if_true` 有三种形态：`matching_blocks`、`all_of`+`predicates`、`matching_block_tag`。字段全集用 `tools/probes/probe-block-transformer.py` 枚举。

**`offset` 决定这个判据是被转换的方块还是环境前提**：带 `offset` 表示「该位置的方块是空」，属环境前提；无 `offset` 才是源方块。把 `air` 当源方块会让「泥土 → 耕地」变成「空气 → 耕地」，路径必然中断（[ADR 0007](adr/0007-transforms-and-tools.md)）。

**逆变换**：有的表声明为另一张表的 inverse，方向须翻转。

**由构造器参数驱动的表不抽取**：形态是 `表.put(参数, this)`，参数是变量而非字面量，按「不做构造器推断」的边界处理，逐表记台账。

## 挖掘机制（代码侧数值）

**位置**：输入包的反编译源码。方块只在 `Blocks.java` 注册，工具只在 `Items.java` 声明；两类都按**调用形态**定位，不按类名或字段名。

| 环节 | 形态 | 读法 |
|---|---|---|
| 方块硬度 | `Properties` 链 | `strength(a[, b])` / `destroyTime(a)` / `instabreak()`；缺省 0.0；`-1` 表示挖不动 |
| 复制 | `ofLegacyCopy` / `ofFullCopy` / `copy`（旧版） | 只继承硬度、爆炸抗性、`requiresCorrectToolForDrops` |
| 复制包装（26.3） | `registerStair` / `registerWall` / `registerSlab` / `registerLegacyStair` | 底方块 + `registerSlab` 的可选硬度覆盖 |
| 集合注册（26.3） | `ColorCollection.registerBlocks` / `zipMap`、`WeatheringCopperCollection.registerBlocks` | 16 色、4 态 × (未涂蜡 / 涂蜡) |
| 辅助工厂（1.18.2） | `Blocks.log(...)` / `leaves(...)` / `bed(...)` / `stainedGlass(...)` | `Properties` 在方法体里，按返回方块的静态工厂展开 |
| 构造器改写 | 构造器对同一个 `Properties` 就地改写 | 实测只有侵染方块：`destroyTime(host.defaultDestroyTime() / 2)`、抗爆 0.75 |
| 工具速度（26.3） | 物品组件 `DataComponents.TOOL` | `new Tool(List.of(Rule...), default, ...)`，规则按声明顺序生效 |
| 工具速度（1.18.2） | `Tier.getSpeed()` + 工具类的 `getDestroySpeed` 覆写 | 方块在工具标签内取材料速度，否则 1.0；等级门槛另记 |

**规则是有序的**：先命中先返回。`speed: null` 只声明「是否算正确工具」，不改速度；`Float.MAX_VALUE` 一类哨兵原样保留，不折算。

**对账**：解析出的方块集合必须等于 `registry` 事实的 `minecraft:block`，工具集合必须是 `minecraft:item` 的子集。多出来的 id 剔除并留台账，缺的记失败——集合展开漏一色、复制包装漏一种，只会表现成「表里少了些行」，而行数本身随版本变化。

**挖掘进度**：每 tick 进度 = `玩家速度 / hardness / (正确工具 ? 30 : 100)`，累计到 1 破坏；`-1` 时进度恒为 0。玩家侧的效率、急迫、疲劳与水中/空中修正取自 `Player.getDestroySpeed` 的常量，取不到的记 `partial`。判据与取舍见 [ADR 0015](adr/0015-mining-mechanics.md)。

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

**各族的判据**（形态、边界、何时不留痕）见对应的 ADR：[代码侧获取关系的提取](adr/0008-code-side-extraction.md)、[交易](adr/0006-trades.md)、[结构内容与模板绑定](adr/0004-structure-and-template-bindings.md)、[实体来源与行为产出](adr/0005-entity-sources-and-behaviour.md)、[世界生成的引用形态与代码侧补全](adr/0003-worldgen-and-references.md)、[方块变换与工具要求](adr/0007-transforms-and-tools.md)。

## 事实种类与族级不可用

**族级不可用**用 `FactStore.mark_unavailable` 登记，**不写台账**——写台账会让覆盖率分母虚高。缺一个报告、缺一个目录都属于这一类，而不是「产出 0 条」。

**归因按类统计**用 `tools/gaps/gap-reasons.py`：`unobtainable` 与 `no_rule` 的分界靠例外表，其余归因由求解结果直接给出。

**扫描不到的东西必须显式登记**：只有 `type` 的配方、`dynamic` 战利品条目、数据包内无引用点的代码绑定，一律留痕。

**不做的几类**是边界决定，不是待办：构造器参数推断（参数是枚举不是被转换的方块）、代码里的任意 `setBlock`（上下文差异大，未逐条核实）、未核实的交互转换。它们的判据在 ADR 里，新增时先确认是否落在边界外。

**枚举型字段的全集来自注册表**，可机器导出，因此覆盖率闸门不需要人工维护白名单。计数须先提取注册名字面量再去重：注册方法体内的那一次也会被计入，类文件数也不等于注册名数。
