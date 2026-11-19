# ADR 0005：实体来源与行为产出

实体的获取链有两个环节：实体本身从哪来，以及它产出什么。两处都不能只靠数据包——世界生成事实只覆盖按群系或结构刷新的实体，产出一律不在数据里。

## 一、行为产出用声明式表，不写成 idiom

`idioms/` 下的适配器都是「在反编译源码里认出一个固定代码形状」。行为产出没有共同形状：同样是「实体产出」，龙蛋走 `setBlockAndUpdate`、龙息走 `turnBottleIntoItem`、蜜脾走 `dropHoneycomb`、青蛙卵走 `Activity` 的某一步。写一个 idiom 只能抓到其中一两种，抓漏时不报错。

更关键的是**判据口径**：idiom 的产出是「反编译源码取证」，证明的是「阅读反编译源码看到这条路径」。这些项的语义可以直接从游戏行为断言，不需要读懂实现——塞进 idiom 等于把「已知事实」伪装成「反编译源码证据」，混淆两类可信度。

所以用 `knowledge/maps/mechanism/entity_behaviour.json`，字段 `produces` / `form` / `actor` / `inputs` / `basis` / `evidence`，生成的规则是 `bridge:behaviour:{name}:{index}`，body 为 `[actor, *inputs]`，`kind` 由 `form` 定（见下）。

`actor` 可以是任何排序的节点，行为主体不止实体：

| 主体 | 例 |
|---|---|
| 实体 | 海龟产卵、末影龙吐息 |
| 方块 | 铁砧耗损、青蛙卵孵化、幽匿催发体转化 |
| 假设 | 玩家书写、玩家填充地图 |
| 世界 | 树生成时挂蜂巢 |

`assume:` 是为这类条目新增的前缀，语义等价于自由变量。它让「玩家做了什么」有地方落，而不必伪造一个 `entity:player`——那会污染实体注册表统计。

### 产出有两种形态

`form` 分两种，缺省 `yield`：

| form | 语义 | kind / 族 |
|---|---|---|
| `yield` | 行为主体 + 消耗品 → 产出一件新东西 | `yield` / `bridge/entity_behaviour` |
| `transmutes` | 手里那件东西换形态成另一件，没有合成表 | `transmutes` / `bridge/item_conversion` |

`filled_map` 与 `written_book` 属后者：空地图探索后被填充、笔与书签名后成书。它们的合成表是 `map` 与 `writable_book`（配方事实里已有），成品这两条没有任何配方。写 `yield` 会让下游按族名归成「某主体掉了这件东西」，与战利品混成一类，给出的第二个判断就是错的。`transmutes` 的 `inputs` 必须非空——没有输入就没有被换形的那件东西。

`player_head` 从表里删掉：它的 `actor` 只能是 `assume:player`，而机制真正要的是「玩家被闪电苦力怕炸死」那一步。`assume:player` 恒真，写出来的规则等于宣称玩家头无条件可得；不写则落 `no_rule`，由报告指出机制未提取。宁可少一条恒真的假路径。

| 做法 | 错在哪 |
|---|---|
| 把 `filled_map` 写成配方（纸 + 指南针 + 制图台） | 制图台不参与这件事，真实链路是「空地图 → 填充」；写成配方会凭空造出一道工序，并把 `map` 与 `filled_map` 的身份混成一个 |
| 把两条留在 `yield` 只改 `basis` | 规则形状不变，下游仍按战利品归类；错误在族名上，改注释改不到 |
| 给 `player_head` 补一个 `assume:charged_creeper` 让它成立 | 那一步不是分析前提而是机制本身（要玩家死一次），写成假设等于把它从待提取清单里藏起来 |

## 二、实体来源分四类

`knowledge/maps/mechanism/entity_sources.json`，字段 `kind` / `requires` / `pattern` / `basis`。`kind` 与代码里的生成原因对应，选哪一种只由「前置是什么」决定，与实体是否稀有没有关系：

| kind | 例 | body |
|---|---|---|
| `summon` | 凋灵：玩家摆 3 个头 + 4 块灵魂沙 | 摆它要用的东西 |
| `dimension` | 末影龙：固定在末地 | `assume:end` |
| `breed` | 骡：马与驴繁殖 | 两个亲本实体 |
| `event` | 流浪商人、行商羊驼：生成器放置 | 触发者实体或前提假设 |

`summon` 的成员尽量走 tag（`wither_summon_base_blocks`），不枚举方块。`breed` 的两个亲本是必要条件，缺一个机制就不成立。

| 做法 | 错在哪 |
|---|---|
| 把繁殖塞进行为表 | 行为表的 `inputs` 语义是消耗品；写成 inputs 会让骡子看起来消耗一匹马和一头驴 |
| 把代码生成的实体补进世界生成事实 | 生物群系的 `spawners` 里没有这些 id，写进去等于伪造数据 |
| 让行商羊驼直接依赖 `assume:wandering_trader` | 链上看不到「由流浪商人生成」这一步，且商人实体永远是 FALSE |
| 让骡依赖马与驴所在群系的刷怪 | 骡不随群系生成；亲本可及只是繁殖的必要条件，不是这一步本身 |

`event` 的两条与一条假设同源：关掉 `assume:wandering_trader` 时，交易与商人实体一起断——这是正确行为，因为两者确实共用同一前提。

## 三、知识表无版本维度，靠编译期对账

一张表由所有版本共用，条目不带版本条件；资源 id 却随版本增删。不做对账，条目会在没有该内容的版本上照样编成规则，图里凭空多出节点：

- 结论节点不存在：判 FALSE，污染节点与状态统计，结论本身还算安全
- 前提含版本无关节点（`world:`、`assume:`）：规则在**所有**版本恒真，一个该版本根本没有的方块会被判成可得

两个函数因此都接收 `{item, block, entity} → 该版本存在的 id 集合`，按排序对账。其余排序（`tag`、`table`、`station`、`tool`、`enchant`、`structure`、`world`、`assume`、`flag`）由各自的事实或约定保证，不在域约束内。

粒度不对称，因为前提与结论的性质不同：

| 位置 | 该版本不存在时 | 理由 |
|---|---|---|
| `actor` / `inputs` / `requires` | 整条不产 | 前提是必要条件，缺一项机制不成立，留下规则只让 head 恒假 |
| 某个 `produces` / head | 只剔除该条结论 | 同一机制其余产物可能仍然有效 |

漏给注册表集合直接抛 `ValueError`：不做「不传就跳过对账」的默认，那种默认会在某次调用方改动后静默失效。

对账只保证「不造出该版本没有的节点」，不保证「机制描述正确」。`actor: assume:mob_spawn` 这类 body 全为版本无关节点的条目，规则等价于「无条件可得该方块」，是对机制的强断言，只能靠 `basis` / `evidence` 人工核验。

## 四、与例外表的分界

`frogspawn` 一度想进行为族：青蛙确实产出青蛙卵方块。但它**不产出物品**——方块只能在水下孵化，挖碎时战利品表是空的。这条走例外表。

判据：**行为族管「如何获取」，例外表管「确定不可获取」**。一个物品若在行为族里有 entry 却仍不可达，说明 entry 写错了，不是例外表该管的。

## 后果

- 三个族：`bridge/entity_behaviour`（`yield`）、`bridge/item_conversion`（`transmutes`）与 `bridge/entity_source`（`spawns`）
- 对账不通过的条目进 `entity_behaviour_problems` / `entity_source_problems`，键形如 `name:unknown_node`
- 新增实体来源不会凭空造物品路径：物种自身的战利品表仍要存在，这里只补「实体从哪来」
