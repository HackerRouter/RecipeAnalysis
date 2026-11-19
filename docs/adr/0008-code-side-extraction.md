# ADR 0008：代码侧获取关系的提取

有些获取路径数据包完全不含，只写在代码里。它们的共同要求是：**判据必须是代码形态，不是类名或名字推断**，推断出来的名字必须与注册表对账。

## 一、结构生成代码里塞进去的物品与实体

`elytra` 是最典型的例子：它既不是配方，也不在任何战利品表里，模板里只有一个 `structure_block` 标记（`nbt.metadata: "Elytra"`）。真正「放一个鞘翅在这儿」的动作写在结构生成器的 `handleDataMarker` 里：

```java
} else if (markerId.startsWith("Elytra")) {
    ItemFrame itemFrame = new ItemFrame(level.getLevel(), position, ...);
    itemFrame.setItem(new ItemStack(Items.ELYTRA), false);
    level.addFreshEntity(itemFrame);
}
```

这不是「掉落」而是「世界里本来就有」，所以是 `holds`（承载者 → 物品），承载者是结构本身。同文件里生成潜影贝的分支属 `spawns`。

判据逐层收窄：

1. 文件含 `handleDataMarker`（两版路径不同，所以按方法名找，不按目录找）
2. 逐个 `markerId.startsWith("X") { 分支体 }`，**只看分支体内部**
3. 分支体里 `new ItemStack(Items.Y)` → `holds`
4. 分支体里 `EntityTypes.Z.create(...)` → `spawns`

**只看分支体**：`BlockPos chestPosition = position.below();` 这类前置代码在分支外，扫进分支会把相邻分支的物品算错。扫描范围要截到该语句的配对右括号。

结构名由类名去 `Pieces` / `Piece` 后缀再转下划线（`EndCityPieces` → `end_city`），属推断，收尾时与 `worldgen` 的结构事实对账，对不上即剔除并留痕。

## 二、生物桶：`via` 与 `inputs` 必须分开

判据：`new MobBucketItem(实体, 流体, ...)`。

```
item:minecraft:tadpole_bucket  ←yield←  entity:minecraft:tadpole (via)
                                        item:minecraft:water_bucket (inputs)
```

`via` 是被装的实体（要它存在，不消耗也不投入），`inputs` 是空桶（必须已有，且会被消耗）。两者混在一个列表里，求解器就分不清「要不要递归求可达」：蝌蚪不存在要去生成，空桶不存在路径就断。

## 三、流体桶：`via` 是被装进去的方块

`new BucketItem(Fluids.X, ...)` 与 `new SolidBucketItem(Blocks.Y, ...)` 同一句式，只是 `via` 换成方块：

```
item:minecraft:lava_bucket  ←yield←  block:minecraft:lava (via)
                                    item:minecraft:bucket (inputs)
```

流体不是实体，绑 `entity:` 是错的；但也不能只留空桶：那样「桶里装的是什么」在下游就消失了，满桶与「空桶重复一遍」在规则上无法区分。

常量名按小写当方块名用（`Fluids.WATER` → `block:minecraft:water`），这是推断。`Fluids` 里有不是方块的常量（`FLOWING_WATER`），所以 `verify_fluid_bucket_blocks` 按 `block` 注册表对账：名字对不上就揟下该 `via` 并留台账。不整条剔除，是因为「空桶 → 满桶」那层仍然成立；也不静默保留，因为不存在的节点恒假，桶会变成不可达而报告只会说「不可获取」。

## 四、目录约定兜底，事实优先

`table_providers.json` 按战利品表路径首段挂产出者。但同一首段下可以混着互不相干的机制——`gameplay/` 里有钓鱼（要钓竿）、猪灵以物易物（要金锭）、袭击后村民送礼、嗅探兽挖掘、若干生物被动产出。一条目录约定把它们全归到 `assume:player`，后果在路径图上直接可见：黑曜石的来源标签只写得出表名，既看不出要付金锭，也看不出这是一次交易。

付款物是源码常量的那几条必须由 idiom 出事实：

```java
public static final Item BARTERING_ITEM = Items.GOLD_INGOT;
LootTable lootTable = ...getLootTable(BuiltInLootTables.PIGLIN_BARTERING);
```

产出 `table:minecraft:gameplay/piglin_bartering ← item:minecraft:gold_ingot`，金锭进 `inputs`。取值顺序是**事实优先于目录约定**，这条事实存在后 `gameplay` 的假设不再作用于该表；约定本身保留，仍要覆盖钓鱼、晨礼等确实没有代码常量的表。

判据：付款物是源码里的常量就走代码抽取；付款物随场景变化又无常量（钓鱼的「鱼竿」、晨礼的「村庄」）才走目录假设。

| 做法 | 错在哪 |
|---|---|
| 把 `gameplay` 整条约定改成一个具名的假设 | 钓鱼、鸡下蛋被一起挂到猪灵身上 |
| 给 `piglin_bartering` 单开一个目录键 | 约定按首段匹配，加二级键会让匹配逻辑变成两套 |
| 把付款物放进 `via` | `via` 是「只需存在不必消耗」，金锭会被当成无限资源 |
| 并进交易族 | 那是职业 + 等级的定价表；以物易物没有职业、没有等级，付款物是单一常量 |

图上不给这个表编中文专名。展示层只汉化**类别**，表名保持原名——表名有几千个且随版本增减，译名表必然不全。区分靠的是**结构**（它有一个金锭上游），不是靠名字。

## 五、适配器约束

- **常量名转注册名要区分写法**：全大写常量直接小写，混合大小写才走驼峰拆分。判错会得到注册表里不存在的名字，且不报错
- **构造参数可能夹带类型转换**：正则要吸收 `(...)` 强制转换段，否则一条也匹配不到
- **锚点必须是调用形态**：裸类名 `LootTable` 会命中几十处 `import`，无一是获取关系。用 `dropFrom\w*LootTable\(`、`BuiltInLootTables\.X`、`spawnAtLocation\(` 这类
- **推断必须对账**：由文件名、类名、字段名推出的节点名一律与对应注册表或事实比对，对不上即剔除并记台账，不留悬空节点
- **找不到目标必须留痕**：缺表、缺方法、匹配数为零都要显式登记，「一条也没有」与「实现漏了」在产物上必须可区分

## 后果

- 新增 idiom `structure_gadgets`、`mob_buckets`、`fluid_buckets`、`piglin_barter`，产出均在 12 种链接种类内
- 结构名、实体名、物品名的对账入口集中在校验模块，避免各处重复推断
- 目录约定仍是绝大多数表的唯一来源，事实只覆盖有代码常量的那些
