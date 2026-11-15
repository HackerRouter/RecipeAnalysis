# ADR 0012：交互来源

一部分物品既没有配方，也不在任何战利品表里，而是「拿某物对某目标用一次」换来的：玻璃瓶取蜂蜜、剪刀剪蜜脾、剪刀剪羊毛、铁桶挤奶。这一族的共同点是**产出者不是物品**，而是「目标 + 触发物」这一对。

不接这一层，图上只看得见这些物品的箱子战利品路径。蜂巢表甚至读得到，却挂不到蜂巢上，于是「表存在」与「拿得到」分家：蜜脾看起来只能开箱得到，蜂蜜瓶只剩一条反向依赖蜂蜜块的配方，牛奶桶只剩试炼密室的补给箱。

## 一、表的触发语义从 `type` 取，持有者从调用形态取

新版战利品表的顶层 `type` 自描述触发方式：`block_interact`、`entity_interact`、`shearing`。这只是「这是哪一类表」，不回答「属于谁」——持有者写在调用点：

```java
BeehiveBlock.dropFromBlockInteractLootTable(level, BuiltInLootTables.HARVEST_BEEHIVE, ...);
this.dropFromEntityInteractLootTable(level, BuiltInLootTables.ARMADILLO_BRUSH, ...);
```

| 做法 | 错在哪 |
|---|---|
| 按表名首段当目标名 | 表名是 Mojang 自己起的自由文本：`harvest/cave_vine` 的方块是 `cave_vines`，`carve/pumpkin`、`till/rooted_dirt` 的目标与首段同形纯属巧合 |
| 把整族记成一条 `assume:player` | 缺了「对什么用」，路径断在假设节点上，且工具前置无处安放 |
| 见到交互表就按 `type` 猜目标种类 | `type` 只说触发方式，抽象基类与接口写下的机制对多个具体类成立，一一对应关系只在代码里 |

持有者因此由 idiom `interact_tables` 从 `dropFrom*InteractLootTable` 调用取，产 `table:X ←holds← block/entity 目标`，`inputs` 放工具。按字面条目的表仍由 `table_providers.json` 兜底，事实优先。

## 二、类名到注册名从注册语句取

交互写在类里，表要挂到**注册名**上，两者不是同一个字符串：

| 类 | 注册名 | 按文件名推会得到 |
|---|---|---|
| `MushroomCow` | `mooshroom` | `mushroom_cow` |
| `CaveVinesBlock` | `cave_vines`、`cave_vines_plant` | 漏掉第二条 |
| `BeehiveBlock` | `beehive`、`bee_nest` | 只留第一条则蜂巢整体失联 |

所以名字一律从 `Blocks.register(...)` / `EntityTypes.register(...)` 的实参取：字面量优先，其次常量类（`BlockItemIds` 的双参数形态同时给出方块名与物品名），都没有才退回字段名并拒绝产出事实。

**一个类可以注册多个名字**，映射是「类 → 名字列表」，只留一条会漏掉同类的另一半方块。

## 三、抽象基类与接口：反向找已注册的子孙

机制不一定写在注册类里：

- `AbstractCow#mobInteract` 写挤奶，`Cow` 与 `MushroomCow` 继承
- `CaveVines.use` 是接口静态方法，`CaveVinesBlock` 与 `CaveVinesPlantBlock` 都实现它

抽象基类与接口没有注册名，所以不能正向查。反向沿 `class X extends Y` 与 `implements` 找**已注册**的子孙，把机制挂到每个子孙上。父链按需读取并缓存，不扫全量目录。

## 四、工具判断取方法体，不取最内层花括号

```java
if (itemStack.is(Items.SHEARS)) {
    BeehiveBlock.dropHoneycomb(...);
}
```

判断写在 `if` 条件里，花括号**内**看不到它；从最内层块起点向前搜会一律落空。取包含调用的**方法体**区间，再在「方法体起点到调用位置」之间找最后一个物品判断。

表调用封进静态方法时（`use` 调 `dropHoneycomb`，表调用在后者里），方法体内没有判断可看，向上看**一跳**调用者。

工具名只认白名单（剪刀、刷子、锄、斧、铲），它们都在 `tool_class.json` 里有定义。其余判断不产前置并记 note：造一个 IR 里没有定义的 `tool:` 节点，会让整条规则恒假，缺口从「缺少工具判断」变成「这条路径不存在」，更难查。

## 五、剪取表走目录约定，不并进 idiom

剪取表的路径规律是「实体名/变体」：`shearing/sheep/white`、`shearing/mooshroom/brown`。首段就是实体注册名，与 `blocks/` `entities/` 同一类约定，因此留在 `table_providers.json`，配 `requires: [tool:minecraft:shears]`。

`requires` 是约定表新增的字段：触发这张表还得有这些东西，直接进 body。没有工具就触发不了，它与「表属于谁」同属硬条件，不是软约束。

入口表 `shearing/sheep` 由 `sheep_shear` 的 `holds` 事实覆盖，事实优先，约定不重复挂。

## 六、没有表的交互进行为表

蜂蜜瓶、牛奶桶、旧版的蜜脾在代码里直接换手持物，不经过战利品表：

```java
if (itemStack.is(Items.GLASS_BOTTLE)) {
    player.setItemInHand(hand, new ItemStack(Items.HONEY_BOTTLE));
}
```

这条与行为表的其他条目同类：证据是「阅读反编译源码看到换手持物」，与龙息、地图填充一样没有共同代码形状。因此写进 `entity_behaviour.json`，`actor` 是目标（`block:beehive`、`entity:cow`），`inputs` 是消耗品（玻璃瓶、铁桶）或工具。

| 做法 | 错在哪 |
|---|---|
| 给「换手持物」写 idiom | 形态在各物品类里互不相同，抓漏不报错 |
| 用 `assume:player` 兜住玻璃瓶 | 看不出对什么用、消耗什么，等价于凭空可得 |

新版数据包已经有对应表的条目（蜜脾），与行为表条目并存：一条来自数据痕迹，一条来自机制本身。两条路径都成立，不去重。

## 后果

- 新族 `code/interact_tables`：交互表的持有者与工具前置
- `table_providers.json` 新增 `requires` 字段，`shearing` 由 `holds_only` 改为按实体首段挂
- 行为表新增交互类条目：蜜脾、蜂蜜瓶、牛奶桶（牛、蘑菇牛、山羊）
- 无 `dropFrom*InteractLootTable` 调用的版本（旧版）该 idiom 命中 0 条，按族级不可用登记；同一批物品由行为表条目覆盖
