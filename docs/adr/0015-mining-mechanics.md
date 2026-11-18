# ADR 0015：挖掘机制的采集（方块硬度与工具速度）

挖掘时间不决定任何物品「拿不拿得到」，RA 的建图与求解完全不读它。这份决策管的是
另一件事：这组数值本身在代码里是一手数据，边界清楚、可以逐条对账，采下来能回答
「挖这块要多久」「同一版本里哪类方块被调硬了」。用既有管道承载它（事实 → 台账 →
`ra export`），比另起一套脚本更省事，也不必再解释一次 provenance。

## 一、单独一类事实

装不进既有种类：`registry` 是「注册表名 + 条目列表」，`profile` 是探测结论，
`code_link` 是获取关系。一条 `mining` 事实是「一个方块 / 一个工具 / 一种材料的
静态数值」，形状与这三者都不同。写成 `code_link` 会被编译层当成可达性规则，
多出从来不存在的工序。

不进 IR，也不改求解器。事实种类只在 `facts/schema.py` 登记，编译层不认它。

## 二、取值来自源码，而不是运行期 dump

两者的权威性相同（都是第一手），选源码是因为：

- **可算**：不需要为每个版本编译一个探针类，也不需要把探针的产物接进 `inputs/`
  的缓存键。源码文本就是输入，事实摘要随之覆盖它。
- **可读**：数值旁边就是声明它的那行代码，`prov` 能指到 `Blocks.java`。
- **与既有 idiom 同构**：`adapters/source/` 已经在做「按调用形态定位 + 台账留痕」，
  这里只是多一个 idiom，不再多一套机制。

运行期 dump 唯一更强的地方是集合注册的展开（颜色、铜态）不必自己推。这些展开规则
在 `ColorCollection` / `WeatheringCopperCollection` 的工厂方法里是常量，按调用名
展开即可；展开结果由注册表全集兜底（见第四节）。

## 三、判据

| 环节 | 判据 | 换一种做法会错在哪 |
|---|---|---|
| 注册点 | `Blocks.java` 与 `Items.java` 的**调用形态**：`Blocks.register*`、`ColorCollection.registerBlocks/zipMap`、`WeatheringCopperCollection.registerBlocks`、`Items.registerItem` | 按类名或字段名扫会把方法体内的复制包装定义当成又一处注册 |
| 硬度来源 | `Properties` 链上的 `strength` / `destroyTime` / `instabreak`，缺省 0.0 | 只认 `strength` 会把 `instabreak()` 与无声明方块都当成缺值 |
| 复制语义 | `ofLegacyCopy` / `ofFullCopy` / `copy` 只继承 `destroyTime`、爆炸抗性、`requiresCorrectToolForDrops` | 整条链一起继承会把别人的声音、光照也带过来，且无法解释「为什么减了这条」 |
| 复制包装 | `registerStair` / `registerWall` / `registerSlab` / `registerLegacyStair` 语义固定：底方块 + 可选硬化覆盖 | 当成普通 `register` 会对不上实参个数，整批楼梯失去硬度 |
| 构造器改写 | 方块构造器对同一个 `Properties` 的就地改写（实测只有 `InfestedBlock`：宿主硬度一半、抗爆 0.75） | 只看注册点的链会把侵染方块记成 0 硬度，而它在游戏里不是秒破 |
| 集合展开 | 颜色 16 项、铜态 4 ×（未涂蜡 / 涂蜡）；注册名从 `BlockItemIds` / `BlockIds` 的常量表来 | 按字段名拼 id 会跟不上 `create("redstone_wire", "redstone")` 这类双参数与 `dye + "_" + base` 的命名 |
| 工具规则 | 26.3 读物品组件 `DataComponents.TOOL` 的 `Rule` 列表；1.18.2 读 `Tier.getSpeed()` + 工具类的 `getDestroySpeed` 覆写 | 只看材料速度会漏掉剑与剪刀的 15 / 5 / 2，只看类名会漏掉材料 |

**规则是有序的**：`Tool.getMiningSpeed` 取第一条「有速度且命中」的规则，
`isCorrectForDrops` 取第一条「有结论且命中」的。事实里保留声明顺序；
`speed: null` 表示这条规则只声明正确性，不改速度。

**不折算常量**：`Float.MAX_VALUE` 原样写成字符串。折算成某个大数之后，
值就不能再与源码逐字对照了，下游也没法判断那是哨兵值还是真的速度。

## 四、对账

解析出的方块 id 集合必须**等于**注册表全集（`registry` 事实的 `minecraft:block`）。
这条比对照数量更强：多出来的 id 说明注册名推错，剔除并留台账；缺的说明有注册形态
没覆盖到，记失败。工具 id 同样与 `minecraft:item` 对账。

没有这层对账，集合展开漏一色、复制包装漏一种，都只会表现成「表里少了些行」——
而行数随版本变化，多一行少一行没人看得出。

## 五、产物

`ra export` 出三张表与一份公式：

| 文件 | 内容 |
|---|---|
| `mining_blocks.jsonl` | 方块 → 硬度、爆炸抗性、是否要求正确工具 |
| `mining_tools.jsonl` | 工具 → 默认速度 + 有序规则（选择器、速度、是否正确工具） |
| `mining_tool_materials.jsonl` | 材料 → 速度、耐久、附魔价值（26.3 另有错误工具标签） |
| `mining_formula.json` | 进度公式：每 tick `玩家速度 / 硬度 / (正确工具 ? 30 : 100)`，累计 ≥ 1 破坏；另有 `-1` 哨兵与玩家侧修正项 |

公式里的玩家侧修正项按方法体里的常量取值；取不到的键进 `missing`，事实标 `partial`，
不用默认值填。
