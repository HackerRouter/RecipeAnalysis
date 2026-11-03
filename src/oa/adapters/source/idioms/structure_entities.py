"""结构生成器里直接生成的实体。

`elytra` 那类「结构里塞物品」由 `structure_gadgets` 覆盖（靠 `handleDataMarker` 的
marker 分支）。本 idiom 覆盖另一形态：**结构拼装器在自己的生成方法里造实体**。

```java
// 26.3 OceanMonumentPieces：远古守卫者房间
if (chunkBB.isInside(pos) && (elder = EntityTypes.ELDER_GUARDIAN.create(
        (Level)level.getLevel(), EntitySpawnReason.STRUCTURE)) != null) { ... }

// 26.3 WoodlandMansionPieces：`case "Mage"` 分支
mobs.add(EntityTypes.EVOKER.create((Level)level.getLevel(), EntitySpawnReason.STRUCTURE));

// 1.18.2 同两处，`create` 只有 Level 一个参数
ElderGuardian elderGuardian = EntityType.ELDER_GUARDIAN.create(worldGenLevel.getLevel());
```

这两处都在 `handleDataMarker` 之外（远古守卫者是 `Room` 的生成方法，唤魔者是
`switch (markerId)` 而不是 `startsWith`），所以 `structure_gadgets` 扫不到。

## 为什么不绑结构名

`OceanMonumentPieces` 对应的结构 ID 是 `monument`，不是 `ocean_monument`；
`WoodlandMansionPieces` 对应 `mansion`。类名与结构 ID 之间没有可复算的映射，
硬推会造出指向不存在结构的节点。

所以前提用假设节点 `assume:structure_content`（「结构里装进去的东西可取得」），
粒度与 `assume:structure_loot` 同级。要精确到结构，得先有可靠的类名 → 结构 ID
对照表，那张表本身就得靠人工维护，与「不写清单」冲突。

## 判据

1. 文件路径含 `/structure/`，且类名以 `Pieces` 结尾（结构拼装器，不是世界生成 feature）
2. `EntityTypes?.<常量>.create(` 的实参里含 `EntitySpawnReason.STRUCTURE` —— 26.3 形态
3. 或者 `create(` 只带一个实参 —— 1.18.2 形态（该版本还没有 `EntitySpawnReason`）

两条判据都不看实体名，所以新版本加了新结构生物也自动覆盖。常量名要在
entity 注册表里，否则留痕不产规则。
"""

from __future__ import annotations

import re

from ....facts import Fact
from ..index import JavaFile, JavaIndex
from .base import Idiom, IdiomResult, Link

ID = "structure_entities"

SPAWN_ASSUMPTION = "assume:structure_content"

# `EntityTypes.EVOKER.create(` / 1.18.2 `EntityType.EVOKER.create(`
CREATE_CALL = re.compile(r"EntityTypes?\.([A-Z][A-Z0-9_]*)\.create\s*\(")

STRUCTURE_REASON = "EntitySpawnReason.STRUCTURE"


def _closing_paren(text: str, open_index: int, limit: int = 600) -> int:
    """`text[open_index]` 是 `(`，返回配对的 `)` 下标；找不到返回 -1。"""
    depth = 0
    for index in range(open_index, min(len(text), open_index + limit)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _is_structure_builder(path: str) -> bool:
    """结构拼装器：路径含 `/structure/`，类名以 `Pieces` 结尾。"""
    if "/structure/" not in path:
        return False
    stem = path.rsplit("/", 1)[-1]
    if not stem.endswith(".java"):
        return False
    return stem[: -len(".java")].endswith("Pieces")


class StructureEntities(Idiom):
    id = ID
    needs = ("structure_entity_reason", "structure_piece_create")
    # 两版各 2 条（elder_guardian + evoker）；低于 2 说明措辞变了。
    min_hits = 2

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        for java in index.files.values():
            if not _is_structure_builder(java.path):
                continue
            self._file(java, result)
        return result

    def _file(self, java: JavaFile, result: IdiomResult) -> None:
        produced = 0
        seen: set[str] = set()
        for match in CREATE_CALL.finditer(java.text):
            constant = match.group(1)
            close = _closing_paren(java.text, match.end() - 1)
            if close < 0:
                result.note(f"{java.path}: {constant} 的 create 调用括号不配对，跳过")
                continue
            args = java.text[match.end() : close]

            # 26.3 要求显式 STRUCTURE；1.18.2 无此枚举，单参形态即结构生成
            single_arg = "," not in args
            if STRUCTURE_REASON not in args and not single_arg:
                continue

            if constant in seen:
                continue
            seen.add(constant)

            result.add(
                Link(
                    head=f"entity:minecraft:{constant.lower()}",
                    kind="spawns",
                    via=(SPAWN_ASSUMPTION,),
                    meta={
                        "carrier": "structure_code",
                        "reason": STRUCTURE_REASON if not single_arg else "单参 create（1.18 形态）",
                    },
                ),
                ID,
                java.path,
                f"{java.path.rsplit('/', 1)[-1]}#create -> EntityTypes.{constant}",
            )
            produced += 1

        if produced == 0:
            result.note(f"{java.path}: 结构拼装器里没有识别到实体生成")


def exported() -> list[Idiom]:
    return [StructureEntities()]
