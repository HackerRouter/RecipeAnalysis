# ADR 0002：事实种类与编译层契约

事实种类与链接种类是阶段之间的接口。两者的共同约束是：**新增一种就多一条翻译路径，漏掉一条即静默丢边，而丢了哪些边在产物上看不见**。因此新增要付代价，且必须显式登记。

## 一、新增事实种类的判据

装不进既有种类时才新增。判据是 payload 形状，不是「这是新东西」：

| 种类 | 为什么装不进既有种类 |
|---|---|
| `components` | 逐条目的属性表，与 `registry` 的「注册表名 + 条目列表」形状不同；也不是探测结论（`profile`），是游戏事实 |
| `block_transform` | 一条事实对应一条变换规则（带 `transformer` / `from` / `to` / `soft`），不是文件；`prov` 指向数据包而非 `.java` |
| `spawner_config` | 一条事实对应一个刷怪笼配置，形状是 `spawn_potentials`（实体 id + 权重） |

同一种语义不能有第二种形状。`block_transform` 的两版来源不同（1.18.2 是 Java 静态表，26.3 是数据包注册表），但事实形状相同，只差 `transformer_kind` 与 `mode` 的取值。

### `components`：`!` 前缀不能照字面读

不能把 `!X: {}` 读成「具有 X 且值为空对象」，否则变体维度推导会多出假维度。表达「不具有」的常规方式是**键缺席**——每个物品只列出它实际具有的组件。

适配器同时接受两种写法，判据是键名前缀而非版本号，因为同一份代码要在多个版本上通用：

| 表达 | 处理 |
|---|---|
| 键缺席 | 视为不具有，`absent` 为空 |
| `!minecraft:X` | 归入 `absent`，绝不进 `components` |

带 `!` 的键即使给了非空值也按「不具有」处理。同时出现 `X` 与 `!X` 时记入 `problems`。

### 族级不可用

版本没有某类报告时，用 `FactStore.mark_unavailable` 登记，**不用空集合代替「没有」**，也不写台账——台账的语义是「每个输入文件一行」，写进去会让覆盖率分母虚高。族级不可用只进 `facts-summary.json` 的 `unavailable_families`。

## 二、链接种类向 12 种收敛

`LINK_KINDS` 落成代码常量，`Link.__post_init__` 越界即 `ValueError`。

自造词意味着编译层需要一张翻译表，翻译表漏一项即静默丢失规则边。实测出现过两类：`place`（`places` 的笔误）与 `drops`（实体装备掉落与 `entities/*` 战利品表同构，都是「产出者 + 条件 → 物品」）。

**为什么硬失败而不是警告**：编译层只认这 12 种，多一种就必须多一条翻译路径；漏项时产物看起来正常，只是可达率偏低。

守卫：`test_kinds_are_from_the_twelve`。

## 三、`profile` 产出为事实

`profile` 声明为事实种类却长期未产出，与「一条也没有」在产物上无法区分。

新增 `adapters/probe_facts.py`，一条事实，`prov.input = "src"`、`prov.file = "data/"`。payload 只承载**决定分派**的判定，不复制全量 Profile——完整 Profile 留在 `profile.json`。分工是「事实流里放判定，快照里放细节」，避免各存一份全量而慢慢分叉。

`profile` 与 `pack_delta` 都不对应单个输入文件，因此不落台账行。

## 四、命中数下限不能当硬门槛

`min_hits` 的本意是防解析退化，不是「本版必须这么大」。机制随版本搬家会让合法命中数远低于另一版本，此时按硬下限判族不可用是错的——事实完全可用。

判据用「上版本非零、本版本归零」这类**相对退化**，不用绝对数字。

## 五、一个目录只有一个负责者

`skip_inert_registries` 把 `data/<ns>/` 下未被 `probe.dirs` 覆盖的目录逐文件登记成「不参与获取路径推理」。新适配器再登记同一批文件就撞台账（实测报「台账重复登记同一文件」）。

所以加 `ADAPTER_DIRS` 白名单，保证一个目录一个负责者。红线 3 的要求是「扫描不到的东西必须显式登记」，不是「两处都登记」。

## 六、标签条目的两处形态

战利品表的 `kind=tag` 条目有两个容易漏的写法，两处漏了都不报错：

### 标签名可能在 `extra.items` 里

条目的 `name` 为 null、标签名在 `extra.items`（`"#minecraft:creeper_drop_music_discs"`）。编译层若先做 `if not isinstance(name, str): continue`，整条被跳过——11 张唱片直接消失。

判据：`kind == "tag"` 且 `name` 为空时，从 `extra.items` 剥掉 `#` 取。

### 标签条目必须展开成成员

`tag` 节点在 IR 里只有一个含义：**其中有任一个**。`bridge/tag` 编的是 `tag ← 成员`，方向是「成员真则 tag 真」。

而战利品表的 tag 条目语义是「**从这堆里随机抽一个**」——tag 真之后每个成员都可能产出。这个方向 `bridge/tag` 给不了。实测出现过 `tag:item/...` 为 TRUE 而它的 11 个成员全为 FALSE。

所以 loot 族把 tag 条目展开成每个成员各一条：

```
item:minecraft:music_disc_11  ←yield←  table:minecraft:entities/creeper
```

依据与 worldgen 的标签放置相同：随机选择 → 每个成员概率非零 → 世界无限 → 每个成员都可能出现。两处共用 `ir/tags.py` 的 `TagMembers`，早先两份实现各自漏过不同写法。

标签不存在或没有可解析成员时记 `unresolved_tag_entries`；成员不在物品注册表时记 `unknown_tag_members`。

## 七、模板方块实体里装着的物品

饰纹陶罐模板的 `nbt` 带陶片 id，这是三种新陶片在数据包里的唯一踪迹：不在任何战利品表里，也不由配方产出。

模板事实新增 `item_refs` 字段（`[{holder, slot, id}]`），IR 编成 `item:X ← block:<holder>`：拆掉陶罐即得。

只取已知键（`sherds` / `Items` / `item` / `Book` / `RecordItem`），不递归猜——方块实体的 `id` 是**方块实体类型**，把它的值当物品会把整棵模板的方块实体都读成物品。
