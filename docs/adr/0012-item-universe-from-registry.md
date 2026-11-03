# ADR 0012：物品全集与可达率分母取自注册表

- 状态：已采纳
- 日期：2026-11-01
- 相关：`src/oa/cli.py` 的 `_item_universe`、`src/oa/report/reachability.py` 的
  `identities`、`knowledge/maps/exceptions/unobtainable.json` 的 `_patterns`

## 背景

物品全集的候选来源有两个：`registries.json` 的 `minecraft:item`（运行期导出）与
`assets/<ns>/items/*.json`（资源文件）。两者不能互相印证，只能留一个。

可达率的分母同理：若取「规则里出现过的 `item:` 节点」，没有规则的物品在规则图上根本
不存在，会从报告里彻底消失。

## 一、`assets` 不是输入需求

服务端 jar 内层只有 3 个 `assets` 文件（`lang`），没有 `items/`：

| 内层 jar | 26.3 | 1.18.2 |
|---|---:|---:|
| `data/` 文件 | 9884 | 4322 |
| `assets/` 文件 | 3 | 2 |
| `assets/items/` | 0 | 0 |

要求用户提供 `assets/` 等于要求他从反编译源码树复制一份数千个文件的目录，只为复现一次已经
通过的等式检查。数据包里没有物品注册表，运行期导出是唯一能给出全集的途径，因此
`registries.json` 单独即可。

`assets/` 仍作为可选输入：提供时逐文件登记台账（红线 3），未提供不视为缺失。
不设 `crosscheck_items`：它唯一的用途就是被否决的第二途径。

## 二、分母必须用注册表全集

拿「规则里出现过的节点」当分母，没有规则的物品在规则图上根本不存在，于是从报告里彻底
消失——总数偏少而不易察觉。这正是红线 3 禁止的静默跳过。

规则节点口径会隐藏几十个物品而报告上只表现为总数偏少，注册表全集口径下不隐藏任何物品。
被隐藏的是刷怪蛋、`command_block_minecart`、`debug_stick` 等零规则物品；
两版的具体偏差见 `oa guide --label <label>` 的「事实与规则产出」一节。

守卫：`test_universe_is_registry_not_rule_nodes`、`test_typed_only_not_in_denominator`、
`test_item_universe_comes_from_registry`。

## 三、成片规律用 `_patterns` 表达

88 个刷怪蛋若逐条写进例外表，就是一份逐物品白名单，与「不写清单」冲突。例外表增加
`_patterns` 段：

```json
"_patterns": [
  {"match": "*_spawn_egg", "category": "创造专属", "basis": "刷怪蛋只在创造模式物品栏提供"},
  {"items": ["minecraft:command_block_minecart", "minecraft:debug_stick"], "category": "创造专属"}
]
```

加载时展开成平表，`attribute()` 的查表逻辑不变。展开只在有全集时进行——通配需要枚举对象。

## 后果

- 可达率按注册表全集计，两个版本的当前数值由 `oa guide --label <label>` 给出
- `no_rule` 计入分母，归因统计涵盖全部物品
- 不设 `adapters.crosscheck_items`、`cli` 的对账打印与 `assets` 的必需性
- `identities` 成为生产必需参数；`test_ir_integration` 与生产走同一路径
- 例外表新增 `_patterns` 段；schema 变更，字段缺失时按无模式处理
