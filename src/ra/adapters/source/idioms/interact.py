"""交互表的持有者：`table:X ←holds← 目标 [+ 工具]`。

## 这一族是什么

26.3 起，Mojang 把「玩家/生物对某物做一次交互，得到若干物品」从散落的
`spawnAtLocation` / `popResource` 搬进了战利品表。这些表的 `type` 自描述：

| 表 `type` | 例子 | 谁触发 |
|---|---|---|
| `block_interact` | `harvest/beehive`、`carve/pumpkin` | 对方块右键 |
| `entity_interact` | `brush/armadillo` | 对实体右键 |
| `shearing` | `shearing/sheep`、`shearing/mooshroom` | 用剪刀剪 |

**表能被读到时不代表它能被拿到**。战利品事实只给「表里有什么」，
不给「表属于谁」。缺这一层，`harvest/beehive` 就是一张无主表，
蜂蜜与蜜脾只在水下遗迹、试炼密室的箱子里出现过——图上看起来像「只能开箱得到」。

## 判据：调用形态，不按表名猜

```java
BeehiveBlock.dropFromBlockInteractLootTable(level, BuiltInLootTables.HARVEST_BEEHIVE, ...);
this.dropFromEntityInteractLootTable(level, BuiltInLootTables.ARMADILLO_BRUSH, ...);
```

调用所在的类就是作用目标。类名到注册名走 `registry_classes`，**不从文件名推**：
`MushroomCow` 的注册名是 `mooshroom`。

两种「不在注册类里」的情况：

- **interface 里的静态方法**：`CaveVines.use` 是 `CaveVinesBlock` 与
  `CaveVinesPlantBlock` 共用的实现，表要挂到两个方块上
- **抽象基类里的方法**：26.3 的挤奶在 `AbstractCow#mobInteract`

两者都靠 `registry_classes.registered_subclasses` 反过来找已注册的子孙。

## 工具：同方法内（或一跳调用者）的物品判断

```java
if (!itemStack.is(Items.SHEARS)) { return InteractionResult.PASS; }
...
PumpkinBlock.dropFromBlockInteractLootTable(...);
```

工具名只认白名单（剪刀、刷子、锄）——它们都在 `tool_class.json` 里，
所以 `tool:minecraft:X` 必然有定义。其余判断不产 `inputs` 并记 note：
产一个 IR 里没有定义的 `tool:` 节点，会让整条规则恒假。

`dropHoneycomb` 这类把表调用包在静态方法里的写法，gate 在**调用者**方法里，
所以「本方法内找不到 gate」时向上看一跳。

## 没有表的交互不在这里

蜂巢产蜂蜜瓶、牛产牛奶在代码里直接换物品，没有表。它们由 `interact_direct`
处理（同一族，证据形态不同）。
"""

from __future__ import annotations

import re

from ..index import JavaFile, JavaIndex
from ..javatext import match_brace
from ..lootconstants import parse_builtin_loot_tables
from ..registry_classes import Registered, registered_subclasses, registry_classes
from .base import Idiom, IdiomResult, Link

ID = "interact_tables"

# `dropFromBlockInteractLootTable` / `dropFromEntityInteractLootTable`
# 不含 `Shearing`：剪取表由 `sheep_shear` 的 holds 与 table_providers 的约定覆盖，
# 这里再产一次会得到同一条边的两个来源。
INTERACT_CALL = re.compile(
    r"dropFrom(BlockInteract|EntityInteract)LootTable\s*\([^;]*?"
    r"BuiltInLootTables\.([A-Z][A-Z0-9_]*)"
)

# 同方法内的物品判断。`itemStack.is(Items.SHEARS)` / `stack.is(ItemTags.HOES)`
ITEM_GATE = re.compile(r"\.is\(\s*Items\.([A-Z][A-Z0-9_]*)\s*\)")
TAG_GATE = re.compile(r"\.is\(\s*ItemTags\.([A-Z][A-Z0-9_]*)\s*\)")

CLASS_DECL = re.compile(r"\bclass\s+([A-Za-z0-9_]+)")
INTERFACE_DECL = re.compile(r"\binterface\s+([A-Za-z0-9_]+)")

# 方法签名：`public static void dropHoneycomb(...)` 到 `{`
METHOD_SIGNATURE = re.compile(
    r"\b(?:public|protected|private)\b[^;{}()]*\b([A-Za-z_][A-Za-z0-9_]*)\s*\("
)

# 白名单：这些工具在 `knowledge/maps/vocabulary/tool_class.json` 里有定义，
# 产出的 `tool:` 节点必然可达。不在表里的判断一律不产 inputs。
TOOL_WHITELIST = {
    "Items.SHEARS": "tool:minecraft:shears",
    "Items.BRUSH": "tool:minecraft:brush",
    "ItemTags.HOES": "tool:minecraft:hoe",
    "ItemTags.AXES": "tool:minecraft:axe",
    "ItemTags.SHOVELS": "tool:minecraft:shovel",
}


def _method_spans(text: str) -> list[tuple[int, int, str]]:
    """`(method_body_open, close, name)` 列表。"""
    spans: list[tuple[int, int, str]] = []
    for match in METHOD_SIGNATURE.finditer(text):
        brace = text.find("{", match.end())
        if brace < 0:
            continue
        close = match_brace(text, brace)
        if close < 0:
            continue
        spans.append((brace, close, match.group(1)))
    return spans


def _span_at(spans: list[tuple[int, int, str]], index: int) -> tuple[int, int, str] | None:
    """包含 `index` 的最内层方法体。"""
    best: tuple[int, int, str] | None = None
    for span in spans:
        if span[0] < index < span[1]:
            if best is None or (span[1] - span[0]) < (best[1] - best[0]):
                best = span
    return best


def _gate_in(segment: str) -> str | None:
    """片段里最后一个白名单工具判断。"""
    hits: list[tuple[int, str]] = []
    for pattern in (ITEM_GATE, TAG_GATE):
        prefix = "Items." if pattern is ITEM_GATE else "ItemTags."
        for match in pattern.finditer(segment):
            node = TOOL_WHITELIST.get(prefix + match.group(1))
            if node is not None:
                hits.append((match.start(), node))
    if not hits:
        return None
    return max(hits)[1]


def _tool_for(text: str, call_index: int) -> tuple[str | None, bool]:
    """表调用需要什么工具。返回 `(节点, 是否来自调用者方法)`。

    先看同方法内、调用之前的判断；没有再找一跳调用者
    （`use` → `dropHoneycomb` 这种把表调用封进静态方法的写法）。
    区间一律取**方法体**，不取最内层 `{}`：`if (stack.is(Items.SHEARS)) {`
    的块起点在判断之后，从块内向前找永远看不见这个判断。
    """
    spans = _method_spans(text)
    span = _span_at(spans, call_index)
    if span is None:
        return None, False
    found = _gate_in(text[span[0] : call_index])
    if found is not None:
        return found, False

    caller_pattern = re.compile(r"(?:\.|\b)" + re.escape(span[2]) + r"\s*\(")
    for match in caller_pattern.finditer(text):
        caller = _span_at(spans, match.start())
        if caller is None or caller[0] == span[0]:
            continue
        found = _gate_in(text[caller[0] : match.start()])
        if found is not None:
            return found, True
    return None, False


def _targets(
    index: JavaIndex,
    registered: dict[str, list[Registered]],
    java: JavaFile,
    parents: dict[str, str | None],
) -> tuple[list[tuple[str, str, bool]], str]:
    """交互所在的类 → `[(排序, 注册名, 是否推断)]`。

    返回 `(目标列表, 类名)`。类名用于留痕。
    """
    cls = java.stem
    direct = registered.get(cls)
    if direct:
        return [(entry.kind, entry.name, entry.inferred) for entry in direct], cls

    def collect(names: list[str]) -> list[tuple[str, str, bool]]:
        return [
            (entry.kind, entry.name, entry.inferred)
            for name in names
            for entry in registered.get(name, ())
        ]

    # interface 的静态方法：实现类不止一个（CaveVines → CaveVinesBlock/PlantBlock）
    if INTERFACE_DECL.search(java.text) and not CLASS_DECL.search(java.text):
        pattern = re.compile(r"\bimplements\b[^{]*\b" + re.escape(cls) + r"\b")
        owners = []
        for name in registered:
            body = index.load(name)
            if body is not None and pattern.search(body.text):
                owners.append(name)
        return collect(sorted(owners)), cls

    # 抽象基类：机制写在基类，注册的是子类
    return collect(registered_subclasses(index, registered, cls, parents)), cls


class InteractTables(Idiom):
    id = ID
    needs = ("dropFromBlockInteractLootTable", "dropFromEntityInteractLootTable")
    # 26.3 实测 5 张 block_interact + 1 张 entity_interact；低于 3 说明匹配退化。
    min_hits = 3

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        constants = parse_builtin_loot_tables(index)
        registered = registry_classes(index)
        parents: dict[str, str | None] = {}

        for java in index.files.values():
            if "InteractLootTable" not in java.text:
                continue
            self._file(java, index, constants, registered, parents, result)
        return result

    def _file(
        self,
        java: JavaFile,
        index: JavaIndex,
        constants,
        registered: dict[str, list[Registered]],
        parents: dict[str, str | None],
        result: IdiomResult,
    ) -> None:
        calls = list(INTERACT_CALL.finditer(java.text))
        if not calls:
            return

        targets, cls = _targets(index, registered, java, parents)
        if not targets:
            result.note(
                f"{java.path}: 交互调用所在的 {cls} 不是注册类，也没有已注册的子类；"
                "表没有持有者，需人工确认"
            )
            return

        for match in calls:
            category, constant = match.group(1), match.group(2)
            table_ids = constants.expand(constant)
            if not table_ids:
                result.note(
                    f"{java.path}: 引用了 BuiltInLootTables.{constant}，"
                    "但常量表里查不到它的注册路径"
                )
                continue

            tool, from_caller = _tool_for(java.text, match.start())
            if tool is None:
                result.note(
                    f"{java.path}: {constant} 附近没有可识别的工具判断，"
                    "按徒手产生前置（不猜工具）"
                )

            inputs = (tool,) if tool is not None else ()
            for sort, name, inferred in targets:
                if inferred:
                    result.note(
                        f"{java.path}: {sort} 注册名 {name} 是从字段名猜的（注册语句里没查到常量或字面量），"
                        "不产表持有关系，需人工确认"
                    )
                    continue
                for table_id in table_ids:
                    result.add(
                        Link(
                            head=f"table:{table_id}",
                            kind="holds",
                            via=(f"{sort}:minecraft:{name}",),
                            inputs=inputs,
                            meta={
                                "category": category,
                                "table_constant": constant,
                                "tool_from_caller": from_caller,
                            },
                        ),
                        ID,
                        java.path,
                        f"{cls}#dropFrom{category}LootTable({constant})",
                    )


def exported() -> list[Idiom]:
    return [InteractTables()]
