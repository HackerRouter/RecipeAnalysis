"""IR 的基本单位：节点与规则。

只有一种形状：

```
rule := { id, head: Node, body: [Node], soft: [Node], kind: LinkKind, meta, family, prov }
```

语义就是一条 Horn 子句：`head` 成立，当且仅当 `body` 全部成立。
- **OR** 由多条同 `head` 的规则表达
- **AND** 由 `body` 表达
- 没有第三种边

## body 与 soft 的分工

| | `body` | `soft` |
|---|---|---|
| 含义 | 获取前提，不成立就不可能 | 世界状态约束，只缩小可行域 |
| 参与判定 | 是 | 否 |
| 例子 | `entity:sheep`、`tool:shears`、`station:furnace` | `sheep/color=white`、`weather=thunder` |

不分开的后果只有两种：把状态约束当硬前置（羊因为「已剪毛」而永远不可剪），
或直接丢弃（产出色别信息丢失）。都不允许。

## 为什么不给来源留类型

「来源」在求解器里不是类型。加一个来源最多影响 `adapters/` 与 `ir/families/`。
`Rule.family` 只用于报告分组与归因展示，求解逻辑不看它。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..facts import Prov

# 12 种链接种类。IR 只认这些；来历与判据见 docs/adr/0002 。
LINK_KINDS = (
    "yield",
    "implies",
    "seeds",
    "holds",
    "places",
    "spawns",
    "transmutes",
    "alias",
    "variants",
    "unlocks",
    "override",
    "assume",
)

# 节点排序（固定小集合）。新增 sort 属契约变更。
SORTS = (
    "item",
    "tag",
    "block",
    "entity",
    "table",
    "station",
    "tool",
    "enchant",
    "structure",
    "world",
    "flag",
    "assume",
)

# 由世界生成事实播种为 TRUE 的排序。
#
# 存在性语义：世界无限，只要生成条件非空，足够大的范围内必然出现。
# 「定义了就是有」，不跑实测、不判群系可否抵达。
SEEDED_SORTS = frozenset({"world", "structure", "entity", "block"})


class NodeError(ValueError):
    """节点格式不合法。"""


def node(sort: str, ident: str) -> str:
    """构造节点 ID。`ident` 已含命名空间时不再补前缀。"""
    if sort not in SORTS:
        raise NodeError(
            f"节点排序 {sort!r} 不在固定集合内：{sorted(SORTS)}"
        )
    if not ident:
        raise NodeError("节点 ID 不能为空")
    return f"{sort}:{ident}"


def split_node(value: str) -> tuple[str, str]:
    """`item:minecraft:iron_ingot` → `("item", "minecraft:iron_ingot")`。"""
    sort, sep, ident = value.partition(":")
    if not sep or sort not in SORTS:
        raise NodeError(f"节点格式不合法：{value!r}")
    return sort, ident


def sort_of(value: str) -> str:
    return split_node(value)[0]


# 注册表名 → 成员的节点排序。
#
# tag 事实里的 `registry` 是注册表全名（`minecraft:item`），而 tag 节点 ID 里
# 用的是短名（`tag:item/minecraft:planks`）。两处必须经同一个函数，
# 否则桥接的 head 与配方引用的 tag 永远对不上——静默失联，一条也连不通。
_REGISTRY_SORTS = {
    "item": "item",
    "block": "block",
    "entity_type": "entity",
    "worldgen/structure": "structure",
}


def tag_node(registry: str, tag_id: str) -> str:
    """`tag:<注册表短名>/<tag id>`。`registry` 可带命名空间。"""
    return node("tag", f"{registry.split(':', 1)[-1]}/{tag_id}")


def registry_sort(registry: str) -> str | None:
    """注册表名 → 成员的节点排序。认不出来时返回 `None`（该 tag 不进 IR）。"""
    return _REGISTRY_SORTS.get(registry.split(":", 1)[-1])


@dataclass(frozen=True)
class Rule:
    """一条 Horn 子句。

    `id` 必须全局唯一且稳定——证明树的确定性排序依赖它（证明树的确定性排序要求：
    优先深度最小，同深度按 `rule.id` 字典序）。
    """

    id: str
    head: str
    body: tuple[str, ...] = ()
    soft: tuple[str, ...] = ()
    kind: str = "yield"
    family: str = ""
    meta: dict = field(default_factory=dict)
    prov: Prov | None = None

    def __post_init__(self) -> None:
        if self.kind not in LINK_KINDS:
            raise NodeError(
                f"链接种类 {self.kind!r} 不在 12 种内：{list(LINK_KINDS)}"
            )
        # head 与 body/soft 必须都是合法节点，且不得自指
        split_node(self.head)
        for value in (*self.body, *self.soft):
            split_node(value)
        if self.head in self.body:
            raise NodeError(f"{self.id}: head 不能出现在自己的 body 里：{self.head}")
        overlap = set(self.body) & set(self.soft)
        if overlap:
            raise NodeError(f"{self.id}: body 与 soft 重叠：{sorted(overlap)}")

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "head": self.head,
            "body": list(self.body),
            "soft": list(self.soft),
            "kind": self.kind,
            "family": self.family,
            "meta": self.meta,
            "prov": self.prov.as_json() if self.prov else None,
        }


@dataclass
class RuleSet:
    """一个版本的规则集合，按 head 建索引。

    同一 head 的多条规则即 OR。`by_head` 是求解器的工作索引，
    `rules` 保留插入顺序以便输出稳定。
    """

    rules: list[Rule] = field(default_factory=list)
    by_head: dict[str, list[Rule]] = field(default_factory=dict)
    _ids: set[str] = field(default_factory=set, repr=False)

    def add(self, rule: Rule) -> None:
        if rule.id in self._ids:
            raise NodeError(f"规则 id 重复：{rule.id}")
        self._ids.add(rule.id)
        self.rules.append(rule)
        self.by_head.setdefault(rule.head, []).append(rule)

    def extend(self, rules: list[Rule]) -> None:
        for rule in rules:
            self.add(rule)

    def of_head(self, head: str) -> list[Rule]:
        return self.by_head.get(head, [])

    def heads(self) -> list[str]:
        return sorted(self.by_head)

    def nodes(self) -> set[str]:
        """出现过的一切节点（head 与 body/soft 合并）。"""
        found: set[str] = set(self.by_head)
        for rule in self.rules:
            found.update(rule.body)
            found.update(rule.soft)
        return found

    def family_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rule in self.rules:
            counts[rule.family] = counts.get(rule.family, 0) + 1
        return dict(sorted(counts.items()))
