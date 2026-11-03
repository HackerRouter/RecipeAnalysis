"""idiom 基类：一个代码惯用法一个提取器，产出既有事实种类。

约束：
1. 产出 `code_link` 事实，形状与其他来源同构（head/body/soft/meta）
2. 声明 `expect`（最小命中数），命中 0 且上版非 0 → 硬失败
3. 每条事实带 `prov`，形如 `Class.java#method`
4. 抽不出来的部分返回 `notes`，由适配器落台账
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ....facts import Fact, Prov
from ..index import JavaIndex

# 12 种链接种类，是 IR 的稳定词汇表。与 ir/nodes.py 的同名常量必须一致。
#
# **不改这里就不许产出新种类**：§4.3 的判据是「新的代码机制如果无法表达成这 12 种
# 之一，先怀疑建模，而不是加种类」。实测踩过：`place` 与 `drops` 曾是自造词，
# 阶段二编译时必须逐个翻译，翻译表一旦漏项就静默丢边。
LINK_KINDS = frozenset(
    {
        "yield",      # 产出者 + 条件 → 物品
        "implies",    # 节点 → 节点（tag 展开、工具等级、别名）
        "seeds",      # 世界/生成器 → 方块、实体、结构、表
        "holds",      # 承载者 → 表/物品
        "places",     # 物品 → 方块
        "spawns",     # 方块/物品 → 实体
        "transmutes", # 物品 + 目标 → 物品/方块
        "alias",      # 承载者沿用另一承载者的产出
        "variants",   # 物品 × 组件值 → 变体身份
        "unlocks",    # 物品/等级 → 能力
        "override",   # overlay 的替换/删除
        "assume",     # 分析假设 → 节点
    }
)


@dataclass(frozen=True)
class Link:
    """一条 code_link 的内容。与 IR 的规则同构，只是来源是反编译源码。

    三类条件必须分开，否则求解时无法区分「要不要递归求可达」：

    | 字段 | 语义 | 求解动作 |
    |---|---|---|
    | `via` | **中介者**：生物、方块、方块实体。只需存在 | 不求可达，作代理节点 |
    | `inputs` | **消耗品**：要投入的物品。耐久不扣也要先有 | 必须递归求可达 |
    | `soft` | **状态条件**：颜色、朝向、是否已用 | 不阻塞可达性，进变体维度 |

    实测教训：剪毛的 `entity:minecraft:sheep` 和 `tool:shears` 曾同放一个
    `body` 列表，语义完全不同——羊不存在只需要生成，剪刀不存在则整条路径断。
    """

    head: str
    kind: str
    via: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    soft: tuple[str, ...] = ()
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in LINK_KINDS:
            raise ValueError(
                f"链接种类 {self.kind!r} 不在 12 种词汇表内："
                f"{sorted(LINK_KINDS)}。"
                "先确认该机制能否用既有种类表达；确需新增走 ADR。"
            )

    def to_fact(self, idiom: str, prov: Prov) -> Fact:
        return Fact(
            kind="code_link",
            payload={
                "idiom": idiom,
                "link": {
                    "head": self.head,
                    "kind": self.kind,
                    "via": list(self.via),
                    "inputs": list(self.inputs),
                    "soft": list(self.soft),
                },
                "meta": self.meta,
            },
            prov=prov,
        )


@dataclass
class IdiomResult:
    links: list[Fact] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def add(self, link: Link, idiom: str, file: str, ptr: str = "") -> None:
        self.links.append(link.to_fact(idiom, Prov(input="src", file=file, ptr=ptr)))
        if file not in self.files:
            self.files.append(file)

    def add_fact(self, fact: Fact, file: str) -> None:
        """直接加一条事实。

        用于产出的不是 `code_link` 的 idiom：方块变换与数据包侧同属
        `block_transform`，形状由那个种类定义，不能套 `code_link` 的壳。
        """
        self.links.append(fact)
        if file not in self.files:
            self.files.append(file)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def fail(self, file: str, error: str) -> None:
        self.failed.append((file, error))


class Idiom(ABC):
    """一个惯用法提取器。"""

    id: str = ""
    needs: tuple[str, ...] = ()
    min_hits: int = 1

    @abstractmethod
    def run(self, index: JavaIndex) -> IdiomResult:
        """在索引上提取。找不到目标文件时返回空结果并说明，不抛异常。"""

    def as_json(self) -> dict:
        return {"id": self.id, "needs": list(self.needs), "min_hits": self.min_hits}
