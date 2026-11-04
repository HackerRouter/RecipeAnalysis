# ADR 0019：模板 NBT 里的实体是实体的来源

- 状态：已采纳
- 日期：2026-11-03
- 相关：`src/ra/ir/families/bindings.py`、`docs/shapes.md`

## 背景

`entity:minecraft:villager` 在两个版本都是零规则、状态 FALSE。它不是孤例问题：
村民**不由任何生物群系的刷怪表生成**（`spawners` 里没有它），也不由任何配方产出，
所以世界生成与配方两条链都覆盖不到它。

后果不只在实体本身。任何以村民为前提的机制会一起断链：

- 代码侧交易（[ADR 0018](0018-code-side-trade-extraction.md)）曾把村民写成
  `via=entity:villager`，于是 1.18.2 的 364 条交易规则全部恒假，附魔书、藏宝图
  一律不可达。这个错误不报任何错，只表现为可达性偏低 11 个百分点。
- `table:minecraft:entities/villager`（村民掉落表）挂不上，虽然该表实际不掉东西。

## 决定

**读模板 NBT 的 `entities` 字段，生成 `entity:X ←seeds← world`。**

模板事实里已经有这个字段，此前只消费了 `blocks`：

```json
{"template": "village/plains/houses/plains_library_1.snbt",
 "entities": [{"id": "minecraft:villager", "has_equipment": true, "blockPos": [2,1,1]},
              {"id": "minecraft:zombie_villager", "has_equipment": true, "blockPos": [4,1,1]}]}
```

与「模板里的方块」（`bindings/template_block`）同一处理：模板是结构的一部分，
结构由世界生成，所以 body 是 `world:overworld`。

**不绑定到具体结构**：模板事实只给模板路径，不含它属于哪个结构。硬推一个结构 ID
会造出不存在的节点——`structure:` 的命名空间与目录名之间没有可复算的映射。

**注册表校验不通过的不静默跳过。** 模板的 `entities` 里也会出现非实体 id
（26.3 的 `minecraft:cushion` 是方块实体），它们进 `unknown_entities`，由编译期
note 指出。

## 换一种做法会错在哪

- **把村民挂到 `assume:*` 了事**：那是「交易这件事可发生」的前提，不是「村民存在」
  的事实。两者混同会让 `ra why` 无法区分「假定能交易」与「结构里有村民」，
  而后者是可复算的数据事实。
- **用刷怪表近似**：村民确实不在刷怪表里。按「哪些生物群系生成村民」去补，
  会得到一个空集，然后被读成「村民不可获得」。
- **推一个结构 ID 当 body**：`village/plains/houses/x.snbt` 属于
  `structure:minecraft:village_plains` 这一步无可复算依据，硬拼会造出假节点，
  比缺一条边更糟（假节点会被当成已覆盖）。
- **只补 `entity:villager` 这一个特例**：同一字段里还有猫、马、铁傀儡、猪灵。
  单点修补会让下一次遇到同类实体时再犯一遍。

## 后果

| | 26.3 | 1.18.2 |
|---|---|---|
| 模板实体种类 | 15 | 12 |
| `bindings` 规则数 | 525 → 540 | 303 → 315 |
| `entity:villager` | 0 → 1 条规则，TRUE | 0 → 1 条规则，TRUE |

可达性数字不变（1535/1658、921/1101）：村民掉落表是空的，交易的可达性已由
假设节点保证。这条改动的收益是**链完整**——`ra why` 现在能追到「结构模板里有村民」
这一层，而不再停在「这条路径不通」。

`entity:villager` 变 TRUE 后新增接上的下游：`table:entities/villager`（空表）。
`minecraft:cushion` 这类非实体 id 按红线 3 留痕，不静默丢。
