"""路径图的呈现参数。

所有旋钮集中在一个不可变对象里，构造时校验——不在各层重复判边界
（`CONTRIBUTING.md`：校验放在构造时，不留给调用方）。

参数分三类，混在一起会让人分不清「减噪」与「减量」：

| 类别 | 参数 | 作用 |
|---|---|---|
| 减噪 | `merge_isomorphic` / `merge_leaves` / `group_min` | 把结构相同的部分合成一条，信息进 tooltip |
| 展开 | `expand_tags` / `expand_conditions` / `expand_groups` | 反方向：把折叠的部分重新铺开 |
| 预算 | `depth` / `branches` / `max_nodes` / `max_groups` | 兜底截断，被截掉的部分画成显式标注 |

参数的**唯一规范**是 `PARAMS`：命令行（`cli.build_parser`）与 HTML 参数表
（`PathOptions.describe`）都从它生成。新增一个旋钮只改一处，否则漏掉的那半
会让图上的参数表复算不出同一张图。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RANKDIRS = ("TB", "BT", "LR", "RL")


@dataclass(frozen=True)
class Param:
    """一个命令行旋钮。类型由 `default` 推出：`bool` 即开关。"""

    name: str
    default: Any
    help: str
    metavar: str | None = None
    choices: tuple[str, ...] | None = None

    @property
    def flag(self) -> str:
        return f"--{self.name.replace('_', '-')}"


# 顺序即 help 与参数表的顺序：预算 → 减噪 → 展开 → 保留 → 布局。
PARAMS: tuple[Param, ...] = (
    Param(
        "depth",
        4,
        "最大展开深度（每条边算一层）。单前件规则已合并成边，"
        "所以 4 层能覆盖「生成 → 方块 → 掉落 → 产物」这类完整链",
    ),
    Param("branches", 4, "聚合组内最多展开几条具体规则（仅 --expand-groups 时生效）；"
          "<=0 表示全部"),
    Param("max_nodes", 500, "节点总数上限"),
    Param("max_groups", 16, "一个节点最多画几个来源类别；<=0 表示不限"),
    Param("group_min", 3, "同一类来源达到几条才聚合成组节点；1 表示全部聚合"),
    Param(
        "merge_isomorphic",
        0,
        "把「只差原料」的同构配方簇折成一条聚合边，N 是簇的最小成员数（0 = 关闭）",
        metavar="N",
    ),
    Param(
        "merge_leaves",
        0,
        "把「同一目标、同一层」的 N 条以上来源边聚成一个计数桶（0 = 关闭）",
        metavar="N",
    ),
    Param("expand_tags", False, "展开 tag 的成员"),
    Param("expand_conditions", False, "展开条件（设备 / 工具 / 附魔）的上游"),
    Param("expand_groups", False, "展开聚合组内部的具体规则"),
    Param("keep_tables", False, "保留 table: 中转节点（默认压进边）"),
    Param(
        "keep_roots",
        False,
        "保留 world / assume 起点节点；默认把起点写进产物节点的标签"
        "（如「草方块 / 主世界生成」）",
    ),
    Param(
        "rankdir",
        "TB",
        "图的走向：TB 从上到下（产物在顶、源头在底），LR 从左到右",
        choices=RANKDIRS,
    ),
)


def default_of(name: str) -> Any:
    """`PARAMS` 里的默认值。字段声明从这里取，避免两处各写一份。"""
    return next(param.default for param in PARAMS if param.name == name)


@dataclass(frozen=True)
class PathOptions:
    """渲染一张路径图的全部参数。默认值见 `PARAMS`。"""

    # 最大展开深度（每条边算一层）。单前件规则已合并成边，
    # 所以 4 层能覆盖「生成 → 方块 → 掉落 → 产物」这类完整链。
    depth: int = field(default=default_of("depth"))
    # 聚合组内最多展开几条具体规则（仅 expand_groups 时生效）；<= 0 表示全部
    branches: int = field(default=default_of("branches"))
    # 节点总数兜底，超过即截断并显式标注
    max_nodes: int = field(default=default_of("max_nodes"))
    # 一个节点最多画几个来源类别；<= 0 表示不限。
    # 与 branches 分开：组的条数是「有几种来源」（信息），
    # 组内条数是「每种来源下有几条规则」（重复），前者不该被后者限死。
    max_groups: int = field(default=default_of("max_groups"))
    # 同一类来源达到几条才聚合成组节点；1 表示全部聚合
    group_min: int = field(default=default_of("group_min"))
    expand_tags: bool = field(default=default_of("expand_tags"))
    expand_conditions: bool = field(default=default_of("expand_conditions"))
    expand_groups: bool = field(default=default_of("expand_groups"))
    # 同构簇折叠的最小成员数；0 = 关闭
    merge_isomorphic: int = field(default=default_of("merge_isomorphic"))
    # 叶子桶的条数门槛；0 = 关闭
    merge_leaves: int = field(default=default_of("merge_leaves"))
    # 保留 table: 中转节点（默认压进边）
    keep_tables: bool = field(default=default_of("keep_tables"))
    # 保留全局起点节点（默认把 world / assume 吸进产物节点的标签）
    keep_roots: bool = field(default=default_of("keep_roots"))
    rankdir: str = field(default=default_of("rankdir"))

    def __post_init__(self) -> None:
        if self.rankdir not in RANKDIRS:
            raise ValueError(f"rankdir 必须是 {RANKDIRS} 之一，收到 {self.rankdir!r}")
        if self.depth < 1:
            raise ValueError(f"depth 至少为 1（不展开就画不出路径），收到 {self.depth}")
        if self.max_nodes < 2:
            raise ValueError(f"max_nodes 至少为 2，收到 {self.max_nodes}")
        if self.merge_isomorphic < 0 or self.merge_leaves < 0:
            raise ValueError("merge_isomorphic / merge_leaves 不能为负；0 表示关闭")
        if self.group_min < 1:
            raise ValueError(f"group_min 至少为 1，收到 {self.group_min}")

    def describe(self) -> list[str]:
        """完整生效配置，一个参数一行，写成原始命令行形式。

        **不做任何加工**：不加中文分组名，不把 `0` 译成「关」，不省略默认值。
        这张表的用途是复算——读者要照着它重跑，或者在图与图之间对比参数。
        一旦开始「帮读者翻译」，就得同时维护一份中文词表，而它只存在于
        展示层，查不到定义；原文则永远与 `build_parser` 一致。

        **写全，不写「与默认值的差」**。图会脱离命令行单独传阅，那时无从知道
        `--depth 4` 是默认还是特意调的。差别不重要，能复算才重要。

        顺序由 `PARAMS` 决定，与命令行 help 的排列一致。
        """
        return [
            f"{param.flag} {getattr(self, param.name)}" for param in PARAMS
        ]
