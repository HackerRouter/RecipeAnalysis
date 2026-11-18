"""挖掘机制的可查表。

一行是一条代码侧静态值，输入只读已落盘的事实，不读 `inputs/`：

| 表 | 一行是 | 用途 |
|---|---|---|
| `mining_blocks` | 一个方块 | 硬度、爆炸抗性、是否要求正确工具 |
| `mining_tools` | 一个带挖掘语义的物品 | 默认速度 + 按方块/标签生效的规则 |
| `mining_tool_materials` | 一种工具材料 | 材料速度（26.3 的 `ToolMaterial`、1.18.2 的 `Tier`） |

另有 `mining_formula.json`：由 `BlockBehaviour.getDestroyProgress` 与
`Player.getDestroySpeed` 的常量得到的进度公式——

```
每 tick 进度 = 玩家速度 / 硬度 / (正确工具 ? 30 : 100)，累计 >= 1 破坏
硬度 = -1 时每 tick 进度恒为 0
```

玩家侧修正项（效率、急迫、疲劳、水中 / 空中）原样列出，取不到的键进 `missing`，
不补默认值。

## 字段口径

- `hardness`：`BlockBehaviour.Properties.destroyTime`，缺省 0.0；`-1` 是「挖不动」，
  此时每 tick 进度恒为 0。
- `rules`：按**声明顺序**生效，先命中先返回。`speed: null` 表示这条规则只声明
  「是否算正确工具」（`correct_for_drops`），不改速度。
  `speed` 可能是字符串（如 `Float.MAX_VALUE`），原样保留，不折算成某个大数——
  折算后的值与源码不再可对照。
- `default_speed`：所有规则都不命中时的速度（`Tool.default_mining_speed`）。
- `drop_level_gates`（仅 1.18.2）：`DiggerItem` 用等级而不是标签表达「挖到了也不掉」，
  一行一个「该标签内的方块至少需要几级」。

每 tick 的进度与破坏阈值见上面的公式；除数与哨兵的具体取值在
`mining_formula.json` 的 `divisors` 与 `unbreakable_hardness`。
"""

from __future__ import annotations

from ..facts import FactStore

TABLE_BLOCKS = "mining_blocks"
TABLE_TOOLS = "mining_tools"
TABLE_MATERIALS = "mining_tool_materials"

TABLE_NAMES = (TABLE_BLOCKS, TABLE_TOOLS, TABLE_MATERIALS)

FORMULA_FILE = "mining_formula.json"

BLOCK_COLUMNS = ("block", "hardness", "explosion_resistance", "requires_correct_tool")
TOOL_COLUMNS = (
    "item",
    "tool_class",
    "material",
    "default_speed",
    "tier_level",
    "rules",
    "drop_level_gates",
)
MATERIAL_COLUMNS = (
    "material",
    "speed",
    "durability",
    "attack_damage_bonus",
    "enchantment_value",
    "incorrect_tool_tag",
    "tier_level",
)


def _mining(store: FactStore, kind: str) -> list[dict]:
    return [
        fact.payload
        for fact in store.of_kind("mining")
        if fact.payload.get("form") == kind
    ]


def build_mining_tables(store: FactStore) -> dict[str, list[dict]]:
    """把 `mining` 事实摊成三张表。缺的列给 null，不补默认值。"""
    blocks = sorted(
        (
            {column: payload.get(column) for column in BLOCK_COLUMNS}
            for payload in _mining(store, "block")
        ),
        key=lambda row: row["block"],
    )
    tools = sorted(
        (
            {column: payload.get(column) for column in TOOL_COLUMNS}
            for payload in _mining(store, "tool")
        ),
        key=lambda row: row["item"],
    )
    materials = sorted(
        (
            {column: payload.get(column) for column in MATERIAL_COLUMNS}
            for payload in _mining(store, "material")
        ),
        key=lambda row: row["material"],
    )
    return {TABLE_BLOCKS: blocks, TABLE_TOOLS: tools, TABLE_MATERIALS: materials}


def mining_formula(store: FactStore) -> dict | None:
    """挖掘进度公式（一条事实）。没有就返回 None，不造空壳。"""
    formulas = _mining(store, "formula")
    if not formulas:
        return None
    payload = dict(formulas[0])
    payload.pop("form", None)
    return payload
