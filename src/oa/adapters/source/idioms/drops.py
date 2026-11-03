"""实体自带装备：生物生成时固定携带的物品。

`ZombieHorse` 带铁矛、`Pillager` 带弩、`Drowned` 带三叉戟——这些装备在实体
初始化时写死，生物死亡后按掉落概率掉出，是物品的获取途径之一。

## 只收字面量

```java
this.setItemSlot(EquipmentSlot.MAINHAND, new ItemStack(Items.IRON_SPEAR));  // ✓ 固定携带
this.setItemSlot(EquipmentSlot.MAINHAND, this.item.copy());                  // ✗ 运行时换手
this.setItemSlot(EquipmentSlot.MAINHAND, ItemStack.EMPTY);                   // ✗ 清空
villager.setItemSlot(EquipmentSlot.MAINHAND, new ItemStack(Items.BONE_MEAL)); // ✗ 在 ai/ 里
```

后三种不是获取途径：`UseBonemeal` 的村民临时拿骨粉，用完即消失。

判据因此是两条，都不靠方法名：

1. 第二个参数是 `new ItemStack(Items.X)` 字面量
2. 文件不在 `world/entity/ai/` 下（那里是 AI 行为，不是实体自身初始装备）

实测 26.3 得 19 处、1.18.2 得 17 处，逐条核对语义都成立。

## 抽象基类不展开

`AbstractSkeleton` 给骷髅配弓，但它是抽象类，注册名不存在对应的实体。
这类跳过并记 note：装备设置被子类继承，展开需要类型层次，属 IR 的事。

## 形状

```
item:minecraft:iron_spear  ←drops←  via: entity:minecraft:zombie_horse
```

`head` 是掉出的物品，`via` 是携带者（生物存在即可）。`inputs` 为空——
掉落不投入任何东西。装备槽与触发方式记在 `meta`。

实体名由文件路径推出，属**推断**，收尾时与 `entity_type` 注册表对账。
"""

from __future__ import annotations

import re

from ..index import JavaFile, JavaIndex
from .base import Idiom, IdiomResult, Link

ID = "drops_source"

LITERAL_SLOT = re.compile(
    r"setItemSlot\s*\(\s*([A-Za-z0-9_.]+)\s*,\s*new\s+ItemStack\s*\(\s*Items\.([A-Z][A-Z0-9_]*)"
)
ABSTRACT_CLASS = re.compile(r"\babstract\s+class\s+([A-Za-z0-9_]+)")

# 实体代码根：`world/entity/`。`ai/` 子目录是 AI 行为，不是实体自身。
ENTITY_ROOT = "net/minecraft/world/entity/"
AI_PREFIX = "net/minecraft/world/entity/ai/"


def _entity_name(path: str) -> str | None:
    """`.../entity/animal/fox/Fox.java` → `fox`。

    驼峰转下划线：`ZombieHorse` → `zombie_horse`。
    """
    stem = path.rsplit("/", 1)[-1]
    if not stem.endswith(".java"):
        return None
    stem = stem[: -len(".java")]
    if not stem or not stem[0].isupper():
        return None
    out: list[str] = []
    for index, ch in enumerate(stem):
        if ch.isupper() and index:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


class EntityEquipmentDrops(Idiom):
    id = ID
    needs = ("setItemSlot 字面量",)
    # 26.3 实测 19 条、1.18.2 17 条；低于 10 说明匹配退化。
    min_hits = 10

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        for java in index.files.values():
            if "setItemSlot" not in java.text:
                continue
            if not java.path.startswith(ENTITY_ROOT) or java.path.startswith(AI_PREFIX):
                continue
            self._file(java, result)
        return result

    def _file(self, java: JavaFile, result: IdiomResult) -> None:
        matches = list(LITERAL_SLOT.finditer(java.text))
        if not matches:
            return

        entity = _entity_name(java.path)
        if entity is None:
            result.note(f"{java.path}: 文件名不像实体类，跳过")
            return

        abstract = ABSTRACT_CLASS.search(java.text)
        if abstract is not None:
            result.note(
                f"{java.path}: {abstract.group(1)} 是抽象类，"
                f"{len(matches)} 处装备设置被子类继承；展开需类型层次，按已知缺口登记"
            )
            return

        for match in matches:
            slot, item = match.group(1), match.group(2).lower()
            line = java.text.count("\n", 0, match.start()) + 1
            result.add(
                Link(
                    head=f"item:minecraft:{item}",
                    kind="yield",
                    via=(f"entity:minecraft:{entity}",),
                    meta={"slot": slot.split(".")[-1], "trigger": "entity_death"},
                ),
                ID,
                java.path,
                f"{entity}#setItemSlot L{line}",
            )


def exported() -> list[Idiom]:
    return [EntityEquipmentDrops()]
