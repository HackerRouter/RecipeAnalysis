"""类名 → 注册名（方块与实体），以及已注册类的继承关系。

交互产出的表必须挂到「作用于什么」上，而作用目标在代码里只以**类**出现：

```java
// 26.3
Block BEEHIVE = Blocks.register(BlockItemIds.BEEHIVE, BeehiveBlock::new, ...);
EntityType<Cow> COW = EntityTypes.register(EntityTypeIds.COW,
        EntityType.Builder.of(Cow::new, ...));

// 1.18.2
Block BEEHIVE = Blocks.register("beehive", new BeehiveBlock(...));
EntityType<Cow> COW = EntityType.register("cow", Builder.of(Cow::new, ...));
```

**不能按文件名推注册名**。多数情况两者只差驼峰与下划线，但实测反例：
`MushroomCow` 的注册名是 `mooshroom`，按文件名会得到 `mushroom_cow`。
所以一律从注册语句取，解析顺序：

1. 注册实参里的字符串字面量（1.18.2 全是这种）
2. `BlockItemIds.X` / `EntityTypeIds.X` 常量（26.3）。前者用
   `BlockItemId.create("方块名", "物品名")` 的双参数形态区分两列，
   后者只有单参数
3. 都查不到才退回字段名小写，并标 `inferred`，由调用方对账

## 继承：交互不一定写在注册类里

26.3 把挤奶搬到 `AbstractCow#mobInteract`，`Cow` 与 `MushroomCow` 继承它。
抽象基类没有注册名，所以反过来查：给定交互所在的类，返回**已注册的**
那个类（含自身）——沿 `class X extends Y` 的父链向上比对。
父链按需读取并缓存，不扫全量目录。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .identifiers import Names, parse_constants
from .index import JavaIndex

__all__ = ["Registered", "registry_classes", "registered_subclasses"]

# `Blocks.register(BlockItemIds.X, FooBlock::new, ...)` / `Blocks.register("foo", new FooBlock(...))`
BLOCK_REGISTER = re.compile(
    r'Blocks\.register\(\s*'
    r'(?:BlockItemIds\.([A-Z][A-Z0-9_]*)|"([a-z0-9_/]+)")\s*,\s*'
    r'(?:new\s+)?([A-Z][A-Za-z0-9_]*)'
)

# `EntityTypes.register(EntityTypeIds.X, EntityType.Builder.of(Foo::new, ...))`
# / `EntityType.register("foo", Builder.of(Foo::new, ...))`
ENTITY_REGISTER = re.compile(
    r'EntityTypes?\.register\(\s*'
    r'(?:EntityTypeIds\.([A-Z][A-Z0-9_]*)|"([a-z0-9_/]+)")\s*,\s*'
    r'(?:EntityType\.)?Builder\.of\(\s*(?:new\s+)?([A-Z][A-Za-z0-9_]*)'
)

# `ARMADILLO = EntityTypeIds.create("armadillo")`
ENTITY_ID_CONST = re.compile(
    r'([A-Z][A-Z0-9_]*)\s*=\s*\w+\.create\(\s*"([a-z0-9_/]+)"\s*\)'
)

CLASS_EXTENDS = re.compile(r"\bclass\s+([A-Za-z0-9_]+)\s+extends\s+([A-Za-z0-9_]+)")

# 父链最多跟这么多跳。MC 的实体层次实测不超过 6 跳；
# 设上限是为了在正则漏配时不至于在环上打转。
MAX_PARENT_DEPTH = 8


@dataclass(frozen=True)
class Registered:
    """一个已注册类。`inferred` 表示注册名是从字段名猜的。"""

    kind: str  # "block" | "entity"
    name: str
    inferred: bool = False


def _entity_type_ids(index: JavaIndex) -> dict[str, str]:
    """`EntityTypeIds` 的常量名 → 注册名。"""
    java = index.load("EntityTypeIds")
    if java is None:
        return {}
    return {name: ident for name, ident in ENTITY_ID_CONST.findall(java.text)}


def _block_name(
    constants: dict[str, Names], constant: str | None, literal: str | None, field: str
) -> tuple[str, bool]:
    if literal:
        return literal, False
    if constant:
        found = constants.get(f"block_item:{constant}")
        if found is not None:
            return found.block, False
    return field.lower(), True


def registry_classes(index: JavaIndex) -> dict[str, list[Registered]]:
    """`{类名: [Registered, ...]}`。方块与实体共用一张表——类名不会重名。

    **一个类可以注册多个名字**，实测 `BeehiveBlock` 同时是 `beehive` 与
    `bee_nest`，`CaveVinesBlock` 同时是 `cave_vines` 与 `cave_vines_plant`。
    交互机制对它们都成立，所以不能只留第一条。
    """
    constants = parse_constants(index)
    entity_ids = _entity_type_ids(index)
    found: dict[str, list[Registered]] = {}

    def add(cls: str, entry: Registered) -> None:
        bucket = found.setdefault(cls, [])
        if entry not in bucket:
            bucket.append(entry)

    blocks = index.load("Blocks")
    if blocks is not None:
        for constant, literal, cls in BLOCK_REGISTER.findall(blocks.text):
            name, inferred = _block_name(constants, constant or None, literal or None, cls)
            add(cls, Registered("block", name, inferred))

    for stem in ("EntityTypes", "EntityType"):
        table = index.load(stem)
        if table is None:
            continue
        for constant, literal, cls in ENTITY_REGISTER.findall(table.text):
            if literal:
                name, inferred = literal, False
            elif constant and constant in entity_ids:
                name, inferred = entity_ids[constant], False
            else:
                name, inferred = cls.lower(), True
            add(cls, Registered("entity", name, inferred))

    return found


def _parent_of(index: JavaIndex, cls: str, cache: dict[str, str | None]) -> str | None:
    if cls in cache:
        return cache[cls]
    java = index.load(cls)
    parent: str | None = None
    if java is not None:
        match = re.search(
            r"\bclass\s+" + re.escape(cls) + r"\s+extends\s+([A-Za-z0-9_]+)", java.text
        )
        if match is not None:
            parent = match.group(1)
    cache[cls] = parent
    return parent


def registered_subclasses(
    index: JavaIndex,
    registered: dict[str, list[Registered]],
    base: str,
    cache: dict[str, str | None] | None = None,
) -> list[str]:
    """`base` 自身及所有**已注册**的子孙类名。

    抽象基类没有注册名（`AbstractCow`），直接按类名查表会失败；
    但它写下的机制对具体子类成立，所以要沿父链把已注册的子孙找出来。
    """
    cache = {} if cache is None else cache
    found: list[str] = []
    for cls in registered:
        current: str | None = cls
        depth = 0
        while current is not None and depth <= MAX_PARENT_DEPTH:
            if current == base:
                found.append(cls)
                break
            current = _parent_of(index, current, cache)
            depth += 1
    return sorted(found)
