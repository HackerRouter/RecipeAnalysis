# ADR 0004：`elytra` 与生物桶的代码来源

- 状态：已采纳
- 日期：2026-10-31
- 相关：`src/oa/adapters/source/idioms/`、`src/oa/adapters/source/verify.py`

## 背景

两条验收在事实层零证据。查清后确认不是「缺 IR」，而是阶段一的洞：这两种物品的
获取路径**数据包完全不含**。

| 物品 | 数据包里的踪迹 | 真正的来源 |
|---|---|---|
| `elytra` | `end_city/ship.snbt` 里一格结构方块标记 `metadata: "Elytra"` | 结构生成代码按标记放物品框 |
| `tadpole_bucket` | 无 | `Items.java` 的 `new MobBucketItem(实体, 流体, ...)` |

## 决定

新增两个 idiom，产出都在 12 种链接种类内。

### `structure_gadgets` → `holds` / `spawns`

判据：文件含 `handleDataMarker`，逐个 `markerId.startsWith("X") { 分支体 }`，
只看**分支体内部**的 `new ItemStack(Items.Y)`（→ `holds`）与
`EntityTypes.Z.create(...)`（→ `spawns`）。

```
item:minecraft:elytra    ←holds←  structure:minecraft:end_city
entity:minecraft:shulker ←spawns← structure:minecraft:end_city
```

结构名由类名推出：去 `Pieces`/`Piece` 后缀再转下划线（`EndCityPieces` → `end_city`），
收尾时与 `worldgen` 事实对账。对账入口 `known_structures()` 是结构名的单一来源。

### `mob_buckets` → `yield`

判据：`new MobBucketItem(实体, 流体, ...)`。

```
item:minecraft:tadpole_bucket ←yield← entity:minecraft:tadpole (via) + item:minecraft:water_bucket (inputs)
```

`via` 是被装的实体（要它存在，不消耗也不投入），`inputs` 是空桶（必须已有，且会被
消耗）。这是 `via` / `inputs` 必须分开的又一例：蝌蚪不存在要去生成，空桶不存在路径就断。

## 四条适配器约束

- **常量名转注册名要区分写法**：全大写常量直接小写，混合大小写才走驼峰拆分。
  判错会得到注册表里不存在的名字，且不报错——推断出来的值必须与注册表对账
- **构造参数可能夹带类型转换**：正则要吸收 `(...)` 强制转换段，否则一条也匹配不到
- **同类常量的前缀随版本变化**：正则要容忍可选的复数后缀，不按某一版的写法写死
- **同一判据不能有两份实现**：测试不要自己重建生产代码已在用的集合或映射，否则
  两版子目录名不同时会分叉，一侧直接失败

## 后果

- `tadpole_bucket` 在 1.18.2 仍然零证据，且这是**正确**的——该版本没有蝌蚪
- 结构名对账收归 `known_structures()` 单一来源
