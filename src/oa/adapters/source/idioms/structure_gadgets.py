"""结构生成代码里塞进去的物品与实体。

`elytra` 是最典型的例子：它既不是配方、也不在任何战利品表里，模板里也只有一个
`structure_block` 标记（`nbt.metadata: "Elytra"`）。真正「放一个鞘翅在这儿」的
动作写在结构生成器的 `handleDataMarker` 里：

```java
} else if (markerId.startsWith("Elytra")) {
    ItemFrame itemFrame = new ItemFrame(level.getLevel(), position, ...);
    itemFrame.setItem(new ItemStack(Items.ELYTRA), false);
    level.addFreshEntity(itemFrame);
}
```

这不是「掉落」而是「世界里本来就有」——所以是 `holds`（承载者 → 物品），
承载者是结构本身。同文件里 `Sentry` 分支生成潜影贝，属 `spawns`。

## 判据

1. 文件含 `handleDataMarker`（两版路径不同：26.3 在 `structure/structures/`，
   1.18.2 在 `structure/`，所以按方法名找，不按目录找）
2. 逐个 `markerId.startsWith("X") { 分支体 }`，只看分支体内部
3. 分支体里 `new ItemStack(Items.Y)` → `holds`
4. 分支体里 `EntityTypes.Z.create(...)` → `spawns`

**只看分支体，不看整段**：`BlockPos chestPosition = position.below();` 这类前置代码
在分支外，扫进分支会把相邻分支的物品算错。

## 结构名怎么来

类名去 `Pieces` / `Piece` 后缀再转下划线：`EndCityPieces` → `end_city`。
属**推断**，收尾时与 `worldgen/structure/*.json` 的 ID 对账，对不上即剔除并留痕。
"""

from __future__ import annotations

import re

from ..index import JavaFile, JavaIndex
from ..javatext import match_brace
from .base import Idiom, IdiomResult, Link

ID = "structure_gadgets"

MARKER_BRANCH = re.compile(r'(\w+)\.startsWith\("([A-Za-z_]+)"\)\s*\)?\s*\{')
ITEMSTACK = re.compile(r"new\s+ItemStack\(\s*Items\.([A-Z][A-Z0-9_]*)")
# 26.3 是 `EntityTypes.SHULKER.create(...)`，1.18.2 是 `EntityType.SHULKER.create(...)`
ENTITY_CREATE = re.compile(r"EntityTypes?\.[A-Z][A-Z0-9_]*\.create\s*\(")
ENTITY_CONST = re.compile(r"EntityTypes?\.([A-Z][A-Z0-9_]*)\.create\s*\(")

CLASS_SUFFIXES = ("Pieces", "Piece")


def _structure_name(path: str) -> str | None:
    """`.../structures/EndCityPieces.java` → `end_city`。"""
    stem = path.rsplit("/", 1)[-1]
    if not stem.endswith(".java"):
        return None
    stem = stem[: -len(".java")]
    for suffix in CLASS_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
            break
    if not stem or not stem[0].isupper():
        return None
    out: list[str] = []
    for index, ch in enumerate(stem):
        if ch.isupper() and index:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def _branches(text: str) -> list[tuple[str, str]]:
    """`handleDataMarker` 里的 `(marker 前缀, 分支体)` 列表。"""
    start = text.find("handleDataMarker")
    if start < 0:
        return []
    body_end = match_brace(text, text.find("{", start))
    body = text[start : body_end if body_end > 0 else len(text)]

    found: list[tuple[str, str]] = []
    for match in MARKER_BRANCH.finditer(body):
        open_index = match.end() - 1
        close = match_brace(body, open_index)
        if close < 0:
            continue
        found.append((match.group(2), body[open_index + 1 : close]))
    return found


class StructureGadgets(Idiom):
    id = ID
    needs = ("handleDataMarker",)
    # 两版实测各 2 条（elytra + shulker）；低于 2 说明匹配退化。
    min_hits = 2

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        for java in index.files.values():
            if "handleDataMarker" not in java.text:
                continue
            self._file(java, result)
        return result

    def _file(self, java: JavaFile, result: IdiomResult) -> None:
        structure = _structure_name(java.path)
        if structure is None:
            result.note(f"{java.path}: 文件名推不出结构名，跳过")
            return

        branches = _branches(java.text)
        if not branches:
            result.note(f"{java.path}: 有 handleDataMarker 但解析不出 marker 分支")
            return

        produced = 0
        for marker, body in branches:
            items = ITEMSTACK.findall(body)
            for item in items:
                result.add(
                    Link(
                        head=f"item:minecraft:{item.lower()}",
                        kind="holds",
                        via=(f"structure:minecraft:{structure}",),
                        meta={"marker": marker, "carrier": "structure_code"},
                    ),
                    ID,
                    java.path,
                    f"{java.path.rsplit('/', 1)[-1]}#handleDataMarker[{marker}] -> Items.{item}",
                )
                produced += 1

            for entity in ENTITY_CONST.findall(body):
                result.add(
                    Link(
                        head=f"entity:minecraft:{entity.lower()}",
                        kind="spawns",
                        via=(f"structure:minecraft:{structure}",),
                        meta={"marker": marker},
                    ),
                    ID,
                    java.path,
                    f"{java.path.rsplit('/', 1)[-1]}#handleDataMarker[{marker}] -> EntityTypes.{entity}",
                )
                produced += 1

            if not items and not ENTITY_CREATE.search(body):
                result.note(
                    f"{java.path}: marker {marker} 的分支里没有物品或实体生成"
                    "（可能是放置方块，属其余族的职责）"
                )

        if produced == 0:
            result.note(f"{java.path}: marker 分支里没有解析出物品或实体")


def exported() -> list[Idiom]:
    return [StructureGadgets()]
