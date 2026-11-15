"""配方的槽位形状：从已归一的 payload 里找齐所有原料槽。

**原始实现。** BingoItemGrading 的 `src/mcshared/recipe_slots.py` 是同构副本，
两边改动必须同步；后续抽成独立包后再取消同步。

**为什么不能按 serializer 决定「原料在哪」**：锻造、酿造把原料放在 `extra` 的
具名键里，特殊合成用语义名任意起键。可靠的做法是**递归找所有 `{items, tags}`
形状的值**——新增 serializer 只要沿用这个形状就自动兼容，不需要加分支。

**槽内是 OR，槽间是 AND**。一个槽位只能放一样东西，所以槽里的多个物品是
「任选其一」；槽位之间才需要同时满足。可达性模型按槽位展开成多条规则，
成本模型对每槽取一份。
"""

from __future__ import annotations

import itertools
from typing import Iterator

# `crafting_shaped` 的图案尺寸上限：2x2 以内用手工合成栏，超出需要工作台。
HAND_GRID = 2


def iter_ingredient_like(value: object) -> Iterator[dict]:
    """递归找出所有 `{items, tags}` 形状的对象。

    `items` 与 `tags` 至少有一个存在才算，避免把恰好同名的别的字段当原料。
    """
    if isinstance(value, dict):
        if "items" in value or "tags" in value:
            yield value
        for sub in value.values():
            yield from iter_ingredient_like(sub)
    elif isinstance(value, list):
        for item in value:
            yield from iter_ingredient_like(item)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def ingredient_slots(payload: dict) -> list[list[str]]:
    """配方 → 槽位列表。每槽是可接受的名字（`#` 前缀表示 tag）。

    覆盖 `ingredients`、`key`、`extra` 三种存放位置，因为判断依据是**值的形状**
    而不是它挂在哪个键下。

    实测量级：26.3 共 295 条配方有多选槽位（14%），展开后规则数 2042 → 3017，
    最大笛卡尔积 16，没有爆炸风险。
    """
    slots: list[list[str]] = []
    for blob in iter_ingredient_like(
        {key: value for key, value in payload.items() if key != "result"}
    ):
        choices: list[str] = []
        for ident in blob.get("items") or []:
            if isinstance(ident, str):
                choices.append(ident)
        for ident in blob.get("tags") or []:
            if isinstance(ident, str):
                choices.append("#" + ident.lstrip("#"))
        if choices:
            slots.append(_dedupe(choices))
    return slots


def pattern_needs_table(pattern: object) -> bool:
    """有形状配方的图案是否超出 2x2 手工合成栏。"""
    if not isinstance(pattern, list) or not pattern:
        return False
    rows = [row for row in pattern if isinstance(row, str)]
    height = len(rows)
    width = max((len(row) for row in rows), default=0)
    return height > HAND_GRID or width > HAND_GRID


def expand_slots(slots: list[list[str]]) -> Iterator[tuple[str, ...]]:
    """槽位的笛卡尔积：每个槽选一个。可达性模型按它展开成多条规则。"""
    yield from itertools.product(*slots)
