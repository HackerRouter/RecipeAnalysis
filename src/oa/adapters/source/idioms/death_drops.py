"""实体死亡时直接掉出的物品（不走战利品表）。

`drops_source` 覆盖的是「实体生成时固定携带的装备」，那些要经过装备槽。
本 idiom 覆盖另一形态：死亡时**直接塞一个物品实体**。

```java
// 26.3 WitherBoss#dropCustomDeathLoot
ItemEntity netherStar = this.spawnAtLocation(level, Items.NETHER_STAR);

// 26.3 Leashable（拴绳被剪断或被拴生物死亡时掉回手上）
entity.spawnAtLocation(serverLevel, Items.LEAD);
```

凋灵的下界之星是最典型的例子：`entities/wither.json` 是**空表**（只有
`type` 与 `random_sequence`，没有任何 pool），所以数据包对这条路径一无所知。
`nether_star` 因此长期显示「无任何产出规则」。

## 判据

1. 文件在 `net/minecraft/world/entity/` 下
2. `spawnAtLocation(` 的实参里出现 `Items.X` 字面量

两条都不看方法名之外的东西，也不判上下文（死亡 / 拴绳剪断都是真实产出）。

## 实体名

由文件路径推出，与注册表对账后再用：

- `WitherBoss` → `wither_boss`，不在注册表 → 去掉 `_boss` / `_entity` 类后缀重试 → `wither` 命中
- `Leashable` 是接口，推不出实体 → 用假设节点 `assume:mob_spawn`，
  因为拴绳掉落对任意被拴生物都成立，不该绑到某一个实体上

对不上注册表且不是接口的，留痕不产规则。**推断必须对账**，这条与
`structure_gadgets` 的结构名处理同源。
"""

from __future__ import annotations

import re

from ..index import JavaFile, JavaIndex
from .base import Idiom, IdiomResult, Link

ID = "death_drops"

SPAWN_LITERAL = re.compile(
    # 两版签名不同，逗号段必须可选：
    #   26.3   `spawnAtLocation(level, Items.NETHER_STAR)`
    #   1.18.2 `spawnAtLocation(Items.NETHER_STAR)`
    r"spawnAtLocation\s*\(\s*(?:[^()]*(?:\([^()]*\)[^()]*)*?,\s*)?Items\.([A-Z][A-Z0-9_]*)"
)
# 接口 / 抽象类没有对应的注册实体
TYPE_DECL = re.compile(r"\b(?:public\s+)?(interface|abstract\s+class)\s+([A-Za-z0-9_]+)")

ENTITY_ROOT = "net/minecraft/world/entity/"

# 类名 → 注册名时要剥掉的词缀（`WitherBoss` → `wither`）
CLASS_SUFFIXES = ("Boss", "Entity", "Fclass")

FALLBACK_VIA = "assume:mob_spawn"


def _candidates(path: str) -> list[str]:
    """由类名推注册名，按可信度排序的候选列表。"""
    stem = path.rsplit("/", 1)[-1]
    if not stem.endswith(".java"):
        return []
    stem = stem[: -len(".java")]
    if not stem or not stem[0].isupper():
        return []

    def snake(value: str) -> str:
        out: list[str] = []
        for index, ch in enumerate(value):
            if ch.isupper() and index:
                out.append("_")
            out.append(ch.lower())
        return "".join(out)

    out = [snake(stem)]
    for suffix in CLASS_SUFFIXES:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            out.append(snake(stem[: -len(suffix)]))
    return out


class DeathDrops(Idiom):
    id = ID
    needs = ("spawnAtLocation 字面量",)
    # 26.3 实测 3 条（下界之星 + 拴绳 2 处）；低于 1 说明匹配退化。
    min_hits = 1

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        for java in index.files.values():
            if "spawnAtLocation" not in java.text:
                continue
            if not java.path.startswith(ENTITY_ROOT):
                continue
            self._file(java, result)
        return result

    def _file(self, java: JavaFile, result: IdiomResult) -> None:
        produced = 0
        for match in SPAWN_LITERAL.finditer(java.text):
            item = match.group(1).lower()

            carriers = self._carriers(java, result)
            if not carriers:
                continue
            line = java.text.count("\n", 0, match.start()) + 1
            result.add(
                Link(
                    head=f"item:minecraft:{item}",
                    kind="yield",
                    via=(carriers[0],),
                    meta={
                        "trigger": "entity_death",
                        "literal": f"Items.{match.group(1)}",
                        # 类名推出的候选链，由适配器收尾时按 entity_type 注册表选。
                        # 不在 idiom 内做对账：注册表不在 JavaIndex 里，
                        # 而适配器已经有一条对账路径（verify_drop_refs）。
                        "via_candidates": list(carriers),
                    },
                ),
                ID,
                java.path,
                f"{java.path.rsplit('/', 1)[-1]}#spawnAtLocation L{line}",
            )
            produced += 1

        if produced == 0 and SPAWN_LITERAL.search(java.text):
            result.note(f"{java.path}: 有 spawnAtLocation 字面量但未能确定承载者")

    @staticmethod
    def _carriers(java: JavaFile, result: IdiomResult) -> list[str]:
        """承载者候选链（按可信度降序）。

        `WitherBoss` → `[entity:wither_boss, entity:wither]`：类名与注册名
        不一定相同（凋灵的注册名是 `wither`），所以给链不给单个。

        接口/抽象类直接返回假设节点：`Leashable` 的拴绳掉落对任意被拴生物
        成立，绑到某一个实体上是错的。
        """
        decl = TYPE_DECL.search(java.text)
        if decl is not None:
            kind = "接口" if decl.group(1) == "interface" else "抽象类"
            result.note(
                f"{java.path}: {decl.group(2)} 是{kind}，掉落对任意实体成立，"
                f"承载者用 {FALLBACK_VIA}"
            )
            return [FALLBACK_VIA]

        candidates = _candidates(java.path)
        if not candidates:
            result.note(f"{java.path}: 类名不像实体类，不产规则")
            return []
        return [f"entity:minecraft:{name}" for name in candidates]


def exported() -> list[Idiom]:
    return [DeathDrops()]
