# ADR 0002：新增 `block_transform` 事实种类

- 状态：已采纳
- 日期：2026-11-01
- 相关：`src/ra/facts/schema.py` 的 `KINDS`、`src/ra/adapters/block_transform.py`

## 背景

「拿着 A 对着方块 B 用，B 变成 C」是纯生存路径，来源随版本而不同：

| 版本 | 来源 | 提取途径 |
|---|---|---|
| 1.18.2 | Java 静态字段（`AxeItem.STRIPPABLES` 等） | `code_link` 的 `transforms_source` idiom |
| 26.3 | 数据包注册表 `data/minecraft/block_transformer/*.json` | 独立事实种类 |

26.3 侧是**数据包文件**，形状与 `code_link` 不同：没有 Java 行号，但带 `properties`、
`loot`、`drop_strategy`、`item_damage_per_use` 等运行时参数。硬塞进 `code_link` 会让
`prov` 语义混乱（后者的 `prov.file` 是 `.java`）。`recipe` / `tag` / `worldgen` 也装
不下：区块变换不消耗物品、不是 tag、与地形生成无关。

## 决定

新增事实种类 `block_transform`，一条事实对应**一条变换规则**（不是注册表文件）。
payload 由适配器定义，核心字段是 `transformer` / `from` / `to` / `soft`。

`prov.input = "src"`，`prov.file` 是数据包内的相对路径，`prov.ptr` 是该规则在文件里
的下标（`/0/block_state_provider/rules/3`），满足可复算。

**两版共用同一形状**，只差三个字段的取值：

| 字段 | 数据包侧（26.3） | 代码侧（1.18.2） |
|---|---|---|
| `transformer` | `minecraft:axe` | `net.minecraft.world.item.AxeItem#STRIPPABLES` |
| `transformer_kind` | `registry` | `code_table` |
| `mode` | `rules` | `table` / `inverse` / `color_collection` |

同一种语义不能有第二种形状——这是分层的硬要求，不是整洁偏好。

## 三条判据

### `transformer` 不是「谁触发」

`transformer` 记的是**变换表的位置**。数据包侧的 `minecraft:axe` 是注册表 ID（客观），
代码侧的 `AxeItem` 是类名（客观）；「哪些物品是斧头」需要看 `Items.IRON_AXE = new
AxeItem(...)` 这类注册，属 IR 的代理判定。

同理，随机刻氧化（`WeatheringCopper.NEXT_BY_BLOCK`）与玩家主动剥皮
（`AxeItem.STRIPPABLES`）在事实层形状相同，可达性判定留给 IR。

### `from` 与 `soft` 按 `offset` 分流

`all_of` 内的 predicate 有两种用途：

| predicate | 含义 | 归入 |
|---|---|---|
| 无 `offset` | 被转换的源方块（或 tag） | `from` |
| 有 `offset` | 环境前提（「上方是空气」） | `soft`，写作 `above=tag:minecraft:air` |

26.3 实测 `offset` 只出现在 `matching_block_tag(minecraft:air)` 上（3 处，恒
`[0,1,0]`）。未来若非 `air` 或非 `[0,1,0]`，`soft` 照实记，不擅自归入 `from`。

守卫：`test_tag_with_offset_is_environment_not_source`、
`test_all_of_splits_source_and_environment`。

### 未知字段一律失败

适配器维护字段白名单，遇到白名单外的键即产出 `failed` 事实并记台账，不静默丢弃。
白名单取自实测枚举，清单见 `adapters/block_transform.py` 的常量与
`tools/probes/probe-block-transformer.py` 的输出。

## 后果

- 事实种类从 11 类变为 12 类
- `skip_inert_registries` 的 `ANALYZED_FAMILIES` 需把 `block_transformer` 纳入，
  否则会与台账重复登记
- 1.18.2 无此注册表，由 `code_link` 的 `transforms_source` idiom 覆盖同一语义——
  两版各有其道，下游统一按 `head ← inputs/via` 消费
