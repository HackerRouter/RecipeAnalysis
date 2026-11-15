"""配方 IR：从 facts payload 反序列化。

**原始实现。** BingoItemGrading 的 `src/mcshared/recipe_ir.py` 是同构副本，
两边改动必须同步；后续抽成独立包后再取消同步。

`payload` 是 `mcshared.recipes.normalize_recipe` 的产物（适配器写出），形状固定：

| 键 | 含义 |
|---|---|
| `serializer` | 序列化器，唯一的形状锚点 |
| `result` | `{id, count, components?, derived_from_input?}` |
| `ingredients` | 无序配方的槽位列表 |
| `key` | 有序配方的符号表 |
| `pattern` / `pattern_id` | 图案行 / 纹饰图案 ID（不是原料） |
| `extra` | 具名槽位（`base`/`template`/`reagent`…）与 `fields`（cookingtime 等） |

**反序列化必须解释每一个键。** 没被认识的键进 `unparsed`，由调用方报错或计数，
不静默丢弃——这是「解析不可再漏」的执行点。

原料槽位的识别复用 `recipe_slots`：按**值的形状**递归找 `{items, tags}`，
所以 `extra` 里的具名槽位和 `crafting_special_*` 的语义槽自动覆盖，
不需要按 serializer 加分支。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .recipe_slots import ingredient_slots, pattern_needs_table

# payload 顶层里由本模块显式解释的键。出现之外的键记进 `unparsed`。
KNOWN_KEYS = frozenset(
    {
        "serializer",
        "result",
        "result_field",
        "results",
        "count",
        "output",
        "ingredient",
        "ingredients",
        "key",
        "pattern",
        "pattern_id",
        "group",
        "category",
        "extra",
    }
)

# `extra` 里不是槽位、而是序列化器参数的键。
EXTRA_NON_SLOT = frozenset({"fields"})

# 工作台：3x3 有形状配方需要它，2x2 及以内不需要。
CRAFTING_TABLE = "minecraft:crafting_table"


@dataclass(frozen=True, eq=False)
class Slot:
    """一个原料槽位。槽内 `choices` 是 OR（任选其一），槽位之间是 AND。

    `qty` 是该槽位要几份。`ingredients`/`extra` 的槽位一份；有形状配方的
    符号用量是它在 `pattern` 里出现的次数（3x3 的金粒配方 `#` 出现 9 次）。
    可达性只需要「存在一份」，成本模型才需要 `qty`。
    """

    role: str  # ingredient / key / named
    choices: tuple[str, ...]
    qty: float = 1.0
    symbol: str = ""
    name: str = ""

    @property
    def item_choices(self) -> tuple[str, ...]:
        """只要精确物品（去掉 `#tag`）。"""
        return tuple(choice for choice in self.choices if not choice.startswith("#"))

    @property
    def tag_choices(self) -> tuple[str, ...]:
        return tuple(choice.lstrip("#") for choice in self.choices if choice.startswith("#"))

    def as_dict(self) -> dict:
        out = {"role": self.role, "choices": list(self.choices), "qty": self.qty}
        if self.symbol:
            out["symbol"] = self.symbol
        if self.name:
            out["name"] = self.name
        return out


def _choices(blob: Mapping[str, Any]) -> tuple[str, ...]:
    choices: list[str] = []
    for ident in blob.get("items") or ():
        if isinstance(ident, str) and ident not in choices:
            choices.append(ident)
    for ident in blob.get("tags") or ():
        if isinstance(ident, str):
            tag = "#" + ident.lstrip("#")
            if tag not in choices:
                choices.append(tag)
    return tuple(choices)


@dataclass(frozen=True, eq=False)
class RecipeIR:
    """一条配方的类型化表示。原料、产出、设备、烹饪时间都在这里。"""

    serializer: str
    slots: tuple[Slot, ...]
    result_id: str | None
    result_count: float
    derived_from_input: bool
    fields: tuple[tuple[str, Any], ...]
    pattern_id: str | None
    result_field: str | None
    station: str | None
    # payload 里没被本模块解释的键（正常应为空；非空说明上游加了新字段）
    unparsed: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any], *, station: str | None = None) -> "RecipeIR":
        serializer = payload.get("serializer")
        if not isinstance(serializer, str) or not serializer:
            raise ValueError("payload 缺 serializer")
        unparsed: list[str] = []

        result = payload.get("result")
        result = result if isinstance(result, dict) else {}
        result_id = result.get("id")
        result_count = result.get("count", 1)
        if not isinstance(result_count, (int, float)):
            result_count = 1.0
        if isinstance(payload.get("count"), (int, float)):
            result_count = float(payload["count"])
        derived = bool(result.get("derived_from_input"))

        slots: list[Slot] = []
        for blob in payload.get("ingredients") or ():
            if isinstance(blob, dict):
                choices = _choices(blob)
                if choices:
                    slots.append(Slot(role="ingredient", choices=choices))
        # 有形状配方：符号用量 = 它在 pattern 里出现的次数（3x3 是 9 次）。
        symbol_counts: dict[str, int] = {}
        pattern = payload.get("pattern")
        if isinstance(pattern, list):
            for row in pattern:
                if isinstance(row, str):
                    for symbol in row:
                        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
        for blob in payload.get("key") or ():
            if isinstance(blob, dict):
                choices = _choices(blob)
                if choices:
                    symbol = str(blob.get("symbol") or "")
                    slots.append(
                        Slot(
                            role="key",
                            choices=choices,
                            qty=float(symbol_counts.get(symbol, 1)),
                            symbol=symbol,
                        )
                    )

        extra = payload.get("extra")
        fields: tuple[tuple[str, Any], ...] = ()
        if isinstance(extra, dict):
            for key, value in extra.items():
                if key in EXTRA_NON_SLOT:
                    if key == "fields" and isinstance(value, dict):
                        fields = tuple(sorted(value.items()))
                    continue
                if isinstance(value, dict):
                    choices = _choices(value)
                    if choices:
                        slots.append(Slot(role="named", choices=choices, name=key))
                        continue
                unparsed.append(f"extra.{key}")

        # 兜底：`extra` 之外、也没被上面解释的槽位形状（未来新增存放位置时）。
        covered = {choice for slot in slots for choice in slot.choices}
        for choices in ingredient_slots({k: v for k, v in payload.items() if k != "extra"}):
            if not set(choices) <= covered:
                slots.append(Slot(role="unclassified", choices=tuple(choices)))
                covered.update(choices)

        for key in payload:
            if key not in KNOWN_KEYS:
                unparsed.append(key)

        pattern_id = payload.get("pattern_id")
        pattern_id = pattern_id if isinstance(pattern_id, str) else None
        result_field = payload.get("result_field")
        result_field = result_field if isinstance(result_field, str) else None

        resolved_station = station
        if resolved_station is None and pattern_needs_table(payload.get("pattern")):
            resolved_station = CRAFTING_TABLE

        return cls(
            serializer=serializer,
            slots=tuple(slots),
            result_id=result_id if isinstance(result_id, str) else None,
            result_count=float(result_count),
            derived_from_input=derived,
            fields=fields,
            pattern_id=pattern_id,
            result_field=result_field,
            station=resolved_station,
            unparsed=tuple(unparsed),
        )

    # ------------------------------------------------------------ 派生查询

    def amount_of(self, item: str) -> float:
        """配方里某个精确物品的总用量（同一物品出现在多个槽位时相加）。"""
        return float(sum(slot.qty for slot in self.slots if item in slot.choices))

    def slot_choices(self) -> list[list[str]]:
        """槽位列表（每槽 OR 候选），与 `recipe_slots.ingredient_slots` 等价。"""
        return [list(slot.choices) for slot in self.slots]

    def cookingtime(self) -> float | None:
        value = dict(self.fields).get("cookingtime")
        return float(value) if isinstance(value, (int, float)) else None

    def as_dict(self) -> dict:
        return {
            "serializer": self.serializer,
            "station": self.station,
            "result": {"id": self.result_id, "count": self.result_count},
            "derived_from_input": self.derived_from_input,
            "slots": [slot.as_dict() for slot in self.slots],
            "fields": dict(self.fields),
            "pattern_id": self.pattern_id,
            "result_field": self.result_field,
            "unparsed": list(self.unparsed),
        }
