"""战利品表 → `yield` 规则。

## 表可达，表里的一切都可能拿到

存在性语义：概率不影响「能不能」，只影响「多稀有」。
所以一条表里所有 `kind=item` 的条目各产一条规则，body 只有表节点 + 硬前置，
不因为处于 `alternatives` 的某一支就降低可达性。

这也意味着：**不区分 children 结构**。适配器已把 children 摊平到同层
（`children` 只剩计数），同层所有 item 条目对「是否存在」是等价的。

## 条件分类

`knowledge/maps/vocabulary/condition_kinds.json` 把条件分六类。这里只处理两类：

- `hard` → 转成 body 节点（如 `tool/can_silk_touch` → `enchant:minecraft:silk_touch`）
- 其余 → 进 `meta.conditions`，不参与判定

`unresolved` 与 `combinator` 不静默当 `ignore`：前者是「已知是硬前置但事实里查不到内容」，
后者是「组合器内层被摊平后无法判定」。两者都按规则汇总进 `meta`，
由 compile 层统一落台账——不在这里逐条刷屏。

## 表本身从哪来

表的产出者在 `ir/bridges/mechanics.py` 里接（`table:blocks/x ← block:x` 等）。
本模块只负责「表里有啥」，不猜表属于谁。
"""

from __future__ import annotations

from collections import Counter

from ...facts import Fact
from ..nodes import Rule, node
from ..tags import TagMembers

FAMILY = "loot"

# 硬前置条件 → 节点。只登记实测确认过的。
HARD_CONDITION_NODES = {
    "minecraft:tool/can_silk_touch": "enchant:minecraft:silk_touch",
    "minecraft:tool/can_shear": "tool:minecraft:shears",
}


def normalize_condition(value: str) -> str:
    """把事实里的条件类型归一成注册名。

    两种原始形态都要处理（实测）：

    - `predicate:tool/can_silk_touch` —— predicate 注册表条目，带 `predicate:` 前缀
    - `survives_explosion` —— 内置条件类型，**没有命名空间前缀**

    不补前缀会让整张 `condition_kinds.json` 一条也匹配不上，
    进而把全部条件当成未登记（实测第一次跑就是这样）。
    """
    if value.startswith("predicate:"):
        return f"minecraft:{value[len('predicate:'):]}"
    if ":" in value:
        return value
    return f"minecraft:{value}"


class LootCompileResult:
    """编译结果 + 条件问题汇总。"""

    def __init__(self) -> None:
        self.rules: list[Rule] = []
        self.condition_kinds: Counter = Counter()
        self.unresolved: Counter = Counter()
        self.combinators: Counter = Counter()
        self.dynamic_tables: list[str] = []
        self.unknown_conditions: Counter = Counter()
        # `any_of` 被展开成 OR 规则的次数
        self.combinator_expanded: Counter = Counter()
        # 组合数超过 `MAX_OR_COMBINATIONS` 而放弃展开的表
        self.combinator_overflow: Counter = Counter()
        # 标志条目里标签名查不到成员，或成员不是物品
        self.unresolved_tag_entries: Counter = Counter()
        self.unknown_tag_members: Counter = Counter()


def _entry_conditions(
    entry: dict, result: LootCompileResult, kinds: dict
) -> tuple[list[str], list[list[str]]]:
    """把条目的条件按类别分流。

    返回 `(body, alternatives)`：

    - `body`：所有硬条件（AND），直接进规则 body
    - `alternatives`：`any_of` 里全部可映射的硬条件（OR），调用方要把它们
      展开成同 head 的多条规则

    `any_of` 不能只计数丢掉：`any_of(can_shear, can_silk_touch)` 是树叶与
    蜘蛛网掉落物的真实前置（19 个条目），丢掉之后这些方块看起来「随便挖就掉」，
    路径里缺了一整条条件。OR 在 IR 里的标准表达就是同 head 多条规则，
    所以这里把可行选项交回调用方，而不是自己在一条 body 里编一个假节点。
    """
    body: list[str] = []
    alternatives: list[list[str]] = []
    for raw in entry.get("conditions") or []:
        if not isinstance(raw, dict):
            continue
        raw_type = raw.get("type")
        if not isinstance(raw_type, str):
            continue
        normalized = normalize_condition(raw_type)
        kind = kinds.get(normalized)
        if kind is None:
            result.unknown_conditions[raw_type] += 1
            continue
        result.condition_kinds[kind] += 1
        if kind == "hard":
            mapped = HARD_CONDITION_NODES.get(normalized)
            if mapped is not None:
                body.append(mapped)
            continue
        if kind == "unresolved":
            result.unresolved[raw_type] += 1
            continue
        if kind != "combinator":
            continue

        # 只有 `any_of` 能安全展开：其 terms 是 OR。
        # `all_of` 的 terms 掺了概率/软条件，`inverted` 是否定，两者都保持原样。
        options = _any_of_nodes(raw, normalized, result)
        if options is None:
            result.combinators[raw_type] += 1
        else:
            alternatives.append(options)
            result.combinator_expanded["any_of"] += 1
    return body, alternatives


def _any_of_nodes(
    raw: dict, normalized: str, result: LootCompileResult
) -> list[str] | None:
    """`any_of` 的 terms 全部是可映射硬条件时，返回可选节点；否则 None。

    只要有一项映射不出来（比如 `survives_explosion` 这种软条件），
    整个组合器就不能当成获取前置——那会把软条件误升成硬前置。
    """
    if normalized != "minecraft:any_of":
        return None
    terms = raw.get("terms")
    if not isinstance(terms, list) or not terms:
        return None
    nodes: list[str] = []
    for term in terms:
        ref = term.get("type") if isinstance(term, dict) else term
        if not isinstance(ref, str):
            return None
        mapped = HARD_CONDITION_NODES.get(normalize_condition(ref))
        if mapped is None:
            return None
        nodes.append(mapped)
    return nodes


def compile_loot(
    facts: list[Fact],
    kinds: dict[str, str],
    tags: TagMembers,
    item_ids: set[str],
    harvest: dict[str, tuple[str, ...]] | None = None,
) -> LootCompileResult:
    """战利品表 → `yield` 规则。

    `tags` 用于展开 `kind=tag` 条目（「随机抽一个」，见模块说明）；
    `item_ids` 用于对账标签成员，非物品的成员留痕不产规则。

    `harvest` 是「方块 → 能采集它的工具」的反向索引，由
    `bridges/harvest.py` 从物品的工具组件推导。表名为 `blocks/<方块>` 时，
    该方块的工具要求是这个表里每一条掉落的前提——**它不在战利品表 JSON 里**，
    而是方块属性，所以只能由调用方传进来。
    """
    result = LootCompileResult()

    for fact in facts:
        payload = fact.payload
        table_id = payload.get("table")
        if not isinstance(table_id, str):
            continue
        table = node("table", table_id)
        # `minecraft:blocks/emerald_ore` → `minecraft:emerald_ore`。
        # 命名空间必须跟着走：工具能力表的键是注册名（`minecraft:cobweb`），
        # 丢掉命名空间会让所有方块查不到工具要求，且一条错误也不报。
        namespace, _, rest = table_id.partition(":")
        block_id = (
            f"{namespace}:{rest.split('/', 1)[1]}"
            if rest.startswith("blocks/") and "/" in rest
            else ""
        )
        tools = (harvest or {}).get(block_id, ())

        for pool_index, pool in enumerate(payload.get("pools") or []):
            if not isinstance(pool, dict):
                continue
            for entry_index, entry in enumerate(pool.get("entries") or []):
                if not isinstance(entry, dict):
                    continue
                kind = entry.get("kind")
                name = entry.get("name")

                if kind == "dynamic":
                    # 依赖运行期上下文（如潜影贝掉自身），静态不可判
                    if table_id not in result.dynamic_tables:
                        result.dynamic_tables.append(table_id)
                    continue
                if kind == "empty":
                    continue
                if kind == "loot_table" and isinstance(name, str):
                    # 嵌套表：表引用表
                    result.rules.append(
                        Rule(
                            id=f"loot:{fact.prov.file}#p{pool_index}e{entry_index}:table",
                            head=node("table", name),
                            body=(table,),
                            kind="holds",
                            family=FAMILY,
                            meta={"nested": True},
                            prov=fact.prov,
                        )
                    )
                    continue
                if not isinstance(name, str):
                    # `kind=tag` 的 `expand` 写法把标签名放在 `extra.items` 里，
                    # `name` 是 null。实测 `entities/creeper.json` 的唱片条目就是这样：
                    #
                    #   {"kind": "tag", "name": null,
                    #    "extra": {"expand": true, "items": "#minecraft:creeper_drop_music_discs"}}
                    #
                    # 只看 `name` 会把整条条目跳过，于是 11 张唱片、3 种陶片
                    # 全部没有规则，且不报错——归因显示成「无任何产出规则」。
                    extra_items = entry.get("extra")
                    if kind == "tag" and isinstance(extra_items, dict):
                        raw_items = extra_items.get("items")
                        if isinstance(raw_items, str):
                            name = raw_items.lstrip("#")
                if not isinstance(name, str) or not name:
                    continue

                body, alternatives = _entry_conditions(entry, result, kinds)

                if kind == "item":
                    for suffix, choice in _or_combinations(
                        table, body, alternatives, tools, table_id, result
                    ):
                        result.rules.append(
                            Rule(
                                id=f"loot:{fact.prov.file}#p{pool_index}e{entry_index}{suffix}",
                                head=node("item", name),
                                body=tuple(choice),
                                kind="yield",
                                family=FAMILY,
                                meta={"table": table_id, "entry_kind": kind},
                                prov=fact.prov,
                            )
                        )
                    continue

                if kind != "tag":
                    continue

                # 战利品表的 tag 条目是「从这堆里随机抽一个」，
                # 不是「任意一个成员都行」——那是 `bridge/tag` 的语义。
                # 所以这里必须**展开成每个成员各一条**，不能只发 `tag ← table`：
                # `bridge/tag` 给的是 `tag ← item` 方向，tag 真推不回成员真，
                # 唱片、陶片就会全部停在 tag 上，归因显示成「无任何产出规则」。
                members = tags.members("minecraft:item", name)
                if not members:
                    # 标签不存在或为空：留痕，不产出一条永不成立的规则
                    result.unresolved_tag_entries[f"{table_id}:{name}"] += 1
                    continue
                for member in sorted(members):
                    if member not in item_ids:
                        result.unknown_tag_members[member] += 1
                        continue
                    for suffix, choice in _or_combinations(
                        table, body, alternatives, tools, table_id, result
                    ):
                        result.rules.append(
                            Rule(
                                id=(
                                    f"loot:{fact.prov.file}"
                                    f"#p{pool_index}e{entry_index}:{member}{suffix}"
                                ),
                                head=node("item", member),
                                body=tuple(choice),
                                kind="yield",
                                family=FAMILY,
                                meta={
                                    "table": table_id,
                                    "entry_kind": "tag",
                                    "tag": name,
                                },
                                prov=fact.prov,
                            )
                        )

    return result


# 一条战利品条目最多展开成多少条规则。
#
# `any_of` 选项 × 工具要求的笛卡尔积。实测上限是蜘蛛网的 2×8=16，
# 所以 32 是留一倍余量的护栏：超过就是数据形状变了，要人工看一眼，
# 不能静默截断——截断会让某个选项凭空消失。
MAX_OR_COMBINATIONS = 32


def _or_combinations(
    table: str,
    body: list[str],
    alternatives: list[list[str]],
    tools: tuple[str, ...],
    table_id: str,
    result: LootCompileResult,
) -> list[tuple[str, list[str]]]:
    """把 AND 的 `body` 与若干 OR 组展开成多条 body，并给每条一个 id 后缀。

    IR 只有 AND body 与「同 head 多条规则」两层，所以 OR 必须在这里展开成
    多条规则。展开后每条都是一条独立获取途径，与 `ra why` 的口径一致。
    """
    groups: list[list[str]] = [g for g in alternatives if g]
    if tools:
        groups.append(list(tools))

    if not groups:
        return [("", [table, *body])]

    combos: list[list[str]] = [[]]
    for group in groups:
        combos = [prev + [option] for prev in combos for option in group]
        if len(combos) > MAX_OR_COMBINATIONS:
            result.combinator_overflow[table_id] += 1
            return [("", [table, *body])]

    def merged(extra: list[str]) -> list[str]:
        """去重保序。`any_of` 与工具要求可能给出同一个节点
        （蜘蛛网既有 `can_shear` 又在剑的采集范围内），重复项进 body 会让
        图上出现两条一模一样的入边。
        """
        out: list[str] = [table]
        seen: set[str] = {table}
        for value in (*body, *extra):
            if value in seen:
                continue
            seen.add(value)
            out.append(value)
        return out

    if len(combos) == 1:
        return [("", merged(combos[0]))]
    return [
        (f":or{index}", merged(combo)) for index, combo in enumerate(combos)
    ]
