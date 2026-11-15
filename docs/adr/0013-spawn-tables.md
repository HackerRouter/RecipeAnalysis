# ADR 0013：刷怪表

「某处会刷什么、各多少权重」分散在五处：群系的自然刷怪表、结构的 `spawn_overrides`、试炼刷怪笼配置、模板里的刷怪笼方块实体、袭击波次。前四者形状互不相同，但对下游是同一个问题：**给定一个地点或装置，列出候选实体与相对权重**。袭击则是**按波次给数量**，同一个问题的另一种参数化。

只把实体名接进获取链（现状）会让这些数据只剩「会不会刷」，权重、数量、刷怪类别在适配器里被丢掉。这类信息不影响可达性，但无法从别的层补——数据包一丢，就只能重跑。

## 一、群系与结构共用 `spawns`，按活动种类区分

两者都是「按类别分组的加权条目表」，条目形状归一后完全相同，因此同一个字段名，读时看 `worldgen_kind`。

| 做法 | 错在哪 |
|---|---|
| 给群系另起字段名 | 下游要多写一套列名映射，两处形状一旦漂移就无人发现 |
| 只把群系刷怪写进 `references` | `references` 的语义是「放置了什么」，`slot=entity` 还是兜底值（`type` 键同时出现在多方块提供者里）；权重与类别无处安放 |

`references` 里已有的实体引用保持不动：它承载 `entity ←seeds← world` 这条可达性规则，`spawns` 只供查表。两者重复不冲突，因为一个说「世界里有它」，一个说「哪个群系刷它、权重多少」。

## 二、权重照原样，不折算概率

`weight` 是**同一持有者、同一类别内**的相对值，分母要由消费方按这两列分组求和。适配器折算成百分比会做两件错事：

- 分母取错时看不出来（跨类别求和、跨层级合并都会得到「看起来合理」的数）
- 原值丢失后再也回不去，而原值是数据包的直接事实

数量同理：`count_min` / `count_max` 缺省记 null，不补 1——「没写数量」与「写了一只」是不同事实。

两版的数量字段不同（新版 `count` 整数或 `uniform` 对象，旧版 `minCount` / `maxCount`），归一在这一层完成，下游只见到一对整数。

## 三、模板里的刷怪笼按 NBT 键识别，不按方块名

`SpawnPotentials` / `SpawnData` 两个键只在刷怪笼方块实体上出现，而方块 id 改过名（`mob_spawner` → `spawner`）。按方块名匹配会在改名的那一版整族失效，且失效时静默。

两者并存时只取 `SpawnPotentials`：`SpawnData` 是其中第一项的初值，两个都记会让同一实体在表里出现两次，权重的分母随之偏大。

## 四、代码侧的均匀数组不进这张表

地牢、矿井一类刷怪笼由结构生成代码直接放置，实体表是代码里的等概率数组（`MonsterRoomFeature.MOBS`），没有权重概念。把它们摊成「每条权重 1」会造出一张看起来像权重表的假表，而真实的机制是「从这个数组里均匀取一个」。

这类机制属于行为表（`knowledge/maps/mechanism/`）的范畴，与「数据包给出权重」是两种证据。

## 五、波次是独立的一维，不能折算成总数

袭击的实体表在代码里是「每个实体一个 8 元素数组，下标即波次」。下游要靠它建模难度，所以：

- `wave` 单独成列，不与数量相乘、也不合并成「总量」
- 数量为 0 的波照记：它表示「这一波不刷它」，丢掉后下游无法区分「0 只」与「这一波没有这个实体」
- 数组第 0 位在代码里不被读取（`groupNumber = groupsSpawned + 1`），所以不产行

| 做法 | 错在哪 |
|---|---|
| 只记非零项 | 前半段「没有卫道士」的信息丢失，难度曲线无法还原 |
| 用「总量」一列代替 | 波数由难度决定（简单 3、普通 5、困难 7），总量随难度变化，折算后既不是那一局的真实值，也回不到分波数据 |
| 把奖励波也折进数组 | 奖励波取 `数组[numGroups]`，与难度耦合；它是「第 numGroups+1 波」，写死成某一波会在换难度时错位 |

基础数量与随机增量分开：`count` 是数组值，`getPotentialBonusSpawns` 按难度与波次追加的随机量不进表——那是运行期随机，不是表。

## 六、不祥之兆是三处产物的共同前提

不祥之兆（`trial_omen`，`bad_omen` 会被转成它）同时决定：

| 产物 | 机制 | 事实落点 |
|---|---|---|
| 不祥试炼的怪物 | 玩家靠近时刷怪笼转为不祥，改用 `ominous_config` | `spawn_tables` 的 `tier=ominous` 行带 `requires=assume:ominous` |
| 不祥钥匙 | 不祥配置的 `loot_tables_to_eject` 弹出 `spawners/ominous/trial_chamber/key` | `spawner_config` 的 `eject_tables` |
| 袭击 | 带不祥之兆进村触发 | 波次行带 `requires=assume:raid`，袭击假设的依据写明它来自不祥之兆 |

**不祥宝库不在这张表里**：它是试炼密室 reward 池生成的方块，生成时不看效果；它的前提在**钥匙**上——开箱要 `ominous_trial_key`，钥匙来自不祥试炼的弹出表。把它当成「宝库方块依赖不祥之兆」会把方块生成与开箱前提混为一谈。

表归属同理：`spawners/` 下的表由「完成试炼」持有，不祥那一支另加不祥之兆。所以 `table_providers.json` 的键按**最长前缀**匹配（先试 `spawners/ominous`，再退回 `spawners`），只按首段会让两套前提共用一条。

## 后果

- `worldgen` 事实的 `spawns` 条目扩为 `{category, entity, weight, count_min, count_max}`，群系新增同名字段与 `spawn_costs`
- `spawner_config` 事实补 `eject_tables`、`equipment` 与 `difficulty`（同时存在数、总量、间隔）
- `template` 事实新增 `spawner_potentials`，在模板适配器里追加，不改共用语法层 `mcshared`
- 新 idiom `raid_waves`：`entity ←spawns← assume:raid`，波次与基础数量进 `meta`
- 新增假设 `assume:raid`、`assume:ominous`、`assume:trial_chamber`
- `ra export` 增 `spawn_tables.jsonl`：五处来源统一为 `(holder_kind, holder, category, entity, weight, count_min, count_max, wave, requires)`
- 可达性不受影响：新增字段只供导出；袭击的实体通过 `spawns` 规则进入获取链，替代原先「只有前哨站/府邸」的单点来源
