"""建图之后的减噪 pass：同构折叠、成员层上交、表压缩、起点吸收、叶子桶。

| 层 | 做法 | 在哪 |
|---|---|---|
| L1 | `tag:` 只画节点，标注成员数 | `graph.py` 的 `Builder` |
| L2 | 同 head 的规则按来源类别聚成 folder | 同上 |
| L3 | 同构规则簇折叠 + 成员层上交 | 本模块 |
| L4 | `table:` 中转节点压进边、假设表改名 | 本模块 |
| L5 | 叶子桶 | 本模块 |
| — | 全局起点吸进产物标签 | 本模块 |

各层的判据与「换一种做法会错在哪」见
`docs/adr/0009-report-artifacts.md`；这里只记实现本身的
约束——尤其是 `__init__.build_path_graph` 里那几个不能调换的顺序。

每一遍都在 `PathGraph` 上留计数：折叠是可读性取舍，不是删数据。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...ir.nodes import Rule, split_node
from ...solve.fixpoint import SolveResult, State
from .graph import PathGraph
from .style import (
    DEFAULT_EDGE_COLOR,
    DROP_KINDS,
    ISOMORPHIC_COLOR,
    ROOT_SORTS,
    TABLE_KIND,
    category_of,
    condition_label_text,
    is_condition,
    root_source_label,
    short,
    short_template,
    source_name,
    stacked,
)


# ---------------------------------------------------------------- L3 同构折叠


@dataclass
class Cluster:
    """一簇同构规则：一批产物，各自的获取规则只差一个来源。

    木台阶就是典型：13 种台阶的配方 body 都是 `[<对应的>_planks, 工作台]`，
    去掉原料一项后完全相同，而 13 个原料恰好是 `tag:item/planks` 的 13 个成员。
    """

    tag: str  # 产物的 tag：`tag:item/minecraft:wooden_slabs`
    family: str
    kind: str
    fixed: tuple[str, ...]  # 各成员规则里相同的部分
    members: dict[str, str]  # 产物 → 该产物规则里的来源（一一对应）
    source_tag: str  # 那些来源共同所属的 tag
    rule_ids: frozenset[str] = frozenset()  # 本簇涉及的规则 id
    label: str = ""  # 来源类别名（「合成」「熔炼」……），用在聚合边标签上


def sort_of(value: str) -> str:
    """节点的比较用排序。tag 视为它成员所在的注册表排序。

    `tag:item/oak_logs` 与 `item:oak_planks` 是同一层的东西（都是物品集），
    只按 `tag:` / `item:` 字面比较会把木板这一层整层排除。
    """
    if value.startswith("tag:"):
        rest = value.split(":", 1)[1]          # `item/oak_logs`
        return rest.split("/", 1)[0]           # `item`
    return value.split(":", 1)[0]


def find_isomorphic_clusters(
    rules_by_head: dict[str, list[Rule]], result: SolveResult, *, min_size: int
) -> list[Cluster]:
    """找同构规则簇。判据严格到宁可漏，不可错。

    ## 为什么要传递闭包

    木材链有两层，第二层的来源本身也是 tag：

    ```
    tag:item/oak_logs            ← {oak_log, oak_wood, stripped_oak_log, stripped_oak_wood}
    tag:item/logs_that_burn      ← {oak_logs, birch_logs, …}
    tag:item/logs                ← {logs_that_burn, crimson_stems, warped_stems}
    item:oak_planks              ← tag:item/oak_logs
    item:oak_slab                ← item:oak_planks
    ```

    木板层的 13 个来源分属 `logs_that_burn` 与 `logs` 两个不同 tag，只看直接
    归属会求不交集。做一次「tag 也是 tag 的成员」的传递闭包后，
    `oak_logs` 同时属于 `logs_that_burn` 与 `logs`，链就连起来了。

    ## 必要条件（每条都实测过会误报才加的）

    1. **产物与来源同注册表**，且来源所属的 tag 也在该注册表。不限定会
       把 `tag:block/mineable/pickaxe` 这类「方块属性标签」当成「由什么做成」。
    2. **`body` 里除变化项外必须有固定部分，或变化项本身是 tag**。
       前者是台阶（固定 `工作台`），后者是木板（固定部分为空，但来源是
       `tag:oak_logs`，构成 tag→tag 链）。两条 `world → block` 都不满足。
    3. **一一对应**：产物数 = 来源数。否则是「任意搭配」，合成不了聚合边。
    4. **来源里属于同一 tag 的成员数 ≥ `min_size`**；不足的成员不折叠，
       保持原样（竹子木板不属于 `tag:item/logs`，它单独留着）。
    5. `body` 全为 TRUE，否则折叠掉的分支可能是唯一可行的。
    """
    if min_size <= 0:
        return []

    # tag → 直接成员（含 tag 成员，闭包要用）
    raw: dict[str, set[str]] = {}
    for head, rules in rules_by_head.items():
        if not head.startswith("tag:"):
            continue
        members = {rule.body[0] for rule in rules if len(rule.body) == 1}
        if members:
            raw[head] = members

    def closure(tag: str, seen: frozenset[str] = frozenset()) -> set[str]:
        """tag 的全部叶子成员（沿 tag→tag 递归展开）。"""
        if tag in seen:
            return set()
        out: set[str] = set()
        for member in raw.get(tag, ()):
            if member.startswith("tag:"):
                out |= closure(member, seen | {tag})
            else:
                out.add(member)
        return out

    tags: dict[str, set[str]] = {tag: closure(tag) for tag in raw}

    # 成员 → 直接所属的 tag（含 tag 作为成员的情形），再求祖先闭包：
    # `oak_logs ∈ logs_that_burn ∈ logs` 于是 `oak_logs` 同时算作 `logs` 的成员。
    # 不做这一步，木板层的 13 个来源分属 `logs_that_burn`（10）与 `logs`（2），
    # 求交集为空，链就断在木板这一层。
    parents: dict[str, set[str]] = {}
    for tag, members in raw.items():
        for member in members:
            parents.setdefault(member, set()).add(tag)

    def ancestors(node: str) -> set[str]:
        seen: set[str] = set()
        stack = list(parents.get(node, ()))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(parents.get(current, ()))
        return seen

    in_tag: dict[str, set[str]] = {node: ancestors(node) for node in parents}

    clusters: list[Cluster] = []
    for tag, members in sorted(tags.items()):
        if len(members) < min_size:
            continue
        live = [m for m in members if result.of(m) is State.TRUE]
        if len(live) < min_size:
            continue

        # (family, kind, 去掉变化项后的 body) → 该组里的 (产物, 规则, 变化项)
        buckets: dict[tuple, list[tuple[str, Rule, str]]] = {}
        for member in live:
            for rule in rules_by_head.get(member, []):
                if rule.kind in DROP_KINDS:
                    continue
                if not all(result.of(t) is State.TRUE for t in rule.body):
                    continue
                for index, varied in enumerate(rule.body):
                    if is_condition(varied) or varied == member:
                        continue
                    fixed = tuple(sorted(b for i, b in enumerate(rule.body) if i != index))
                    key = (rule.family, rule.kind, fixed)
                    buckets.setdefault(key, []).append((member, rule, varied))

        for (family, kind, fixed), rows in buckets.items():
            heads = {m for m, _, _ in rows}
            varied = {v for _, _, v in rows}
            if len(heads) < min_size or len(varied) != len(heads):
                continue
            # 产物与来源同层（tag 按它的注册表算，见 `sort_of`）
            if {sort_of(h) for h in heads} != {sort_of(v) for v in varied}:
                continue
            # 条件 2：要么有固定部分，要么来源是 tag（构成 tag→tag 链）
            if not fixed and not all(v.startswith("tag:") for v in varied):
                continue

            # 找一个 tag 覆盖尽可能多的来源；覆盖数不足的不参与折叠。
            cover: dict[str, list[tuple[str, str]]] = {}
            for member, _, value in rows:
                for candidate in in_tag.get(value, ()):
                    cover.setdefault(candidate, []).append((member, value))
            for candidate in list(cover):
                # 排除两类候选：
                #
                # 1. 与产物同一个 tag —— 上蜡/脱蜡这类「批量变换」，
                #    边会变成 `tag:X → tag:X` 自环。
                # 2. 叶子成员包含产物本身 —— 那是「同一批东西的另一个别名」，
                #    不是「由什么做成」。例如 `sulfur_cube_archetype/bouncy`
                #    同时包含原木与木板，`wooden_tool_materials` 的叶子就是
                #    那 13 种木板；用它们当来源会画出
                #    `bouncy → planks` 这种既不准确也难懂的边。
                if candidate == tag:
                    cover.pop(candidate)
                    continue
                if tags.get(candidate, set()) & heads:
                    cover.pop(candidate)
            if not cover:
                continue

            def rank(item: tuple[str, list[tuple[str, str]]]) -> tuple:
                """候选排序：覆盖数优先，其次直接成员全是物品，最后取最具体的。

                第二项：`tag:item/planks` 与 `tag:item/wooden_tool_materials`
                叶子成员完全一样（都是 13 种木板），但后者只有一个 tag 成员，
                语义是「哪些材料能做木质工具」，不是「木板由什么做成」。

                第三项：`tag:item/logs` 与 `tag:item/sulfur_cube_swallowable`
                都能覆盖 12 个原木 tag（后者包含前者），但后者还包着木板、
                竹块，语义更泛。取叶子成员最少的就是最贴近这一层的那一个。
                """
                candidate, pairs = item
                direct = raw.get(candidate, set())
                flat = 0 if any(n.startswith("tag:") for n in direct) else 1
                return (len(pairs), flat, -len(tags.get(candidate, ())), candidate)

            source_tag, pairs = max(cover.items(), key=rank)
            if len(pairs) < min_size:
                continue

            picked = dict(pairs)
            clusters.append(
                Cluster(
                    tag=tag,
                    family=family,
                    kind=kind,
                    fixed=fixed,
                    members=picked,
                    source_tag=source_tag,
                    rule_ids=frozenset(r.id for m, r, _ in rows if m in picked),
                    label=category_of(rows[0][1])[1],
                )
            )

    # 去重：同一批成员会同时属于多个 tag（`planks` 与 `wooden_tool_materials`
    # 的叶子完全一样；`logs` 的方块版本同时属于 7 个属性标签）。同一批成员 +
    # 同一条规则形状只保留一个，取来源 tag 最具体（叶子最少）的那个。
    by_members: dict[tuple, Cluster] = {}
    for cluster in clusters:
        key = (cluster.family, cluster.kind, cluster.fixed, frozenset(cluster.members))
        current = by_members.get(key)
        if current is None or len(tags.get(cluster.source_tag, ())) < len(
            tags.get(current.source_tag, ())
        ):
            by_members[key] = cluster
    return list(by_members.values())


def merge_isomorphic(
    graph: PathGraph,
    clusters: list[Cluster],
    rules_by_head: dict[str, list[Rule]] | None = None,
) -> int:
    """把同构簇收成一条 `来源 tag → 产物 tag` 的边，返回折叠的簇数。

    **折叠会压掉「一一对应」这个信息**：13 种台阶各由对应的木板做成，
    不是「任意木板能做任意台阶」。所以边标签必须写明「13 组一一对应」，
    tooltip 给完整配对表——折叠是默认可读性取舍，不是删数据。

    只在簇的产物成员确实被画进图里时才折叠：那些成员按各自规则铺开，
    数量与菱形数一起膨胀，折叠才有收益。tag 未展开时本来就只有一个节点。
    """
    if not clusters:
        return 0

    # 反复折叠到不再变化：一层折叠会把 `tag:item/planks` 变成新的来源，
    # 上一层（木板 ← 原木）因此变得可折。木材链就是这样连成
    # `tag:logs → tag:planks → tag:wooden_slabs` 的。
    progress = True
    while progress:
        progress = False
        for cluster in clusters:
            if f"iso::{cluster.tag}" in {e[2] for e in graph.edges}:
                continue
            present = [m for m in cluster.members if m in graph.nodes]
            # 判据分两层，缺一层都会误折：
            #
            # 1. **至少 2 个成员在图里**。这是防「上层标签误触发」的：从木台阶
            #    出发时 `tag:item/slabs`（96 组，包着木/羊毛/混凝土三类）只有
            #    木台阶一个成员在图里，折它就会画出 `sulfur_cube_swallowable →
            #    所有台阶` 这种本层不该出现的边。
            #
            # 2. **多数成员「本该」在图里**。这里必须把 `suppressed` 算进来：
            #    默认 `--branches 4` 会把 13 种木台阶只铺开 4 种，只数 present
            #    就永远过不了「一半」这条线，同构折叠等于没开。
            #    而 `tag:item/slabs` 的另外 80 多组成员根本没被预算挡住
            #    （它们不在这条路径上），所以 counted 仍然只有 13 < 48，不会误折。
            if len(present) < 2:
                continue
            counted = present + [
                m for m in cluster.members if m in graph.suppressed and m not in graph.nodes
            ]
            if len(counted) * 2 < len(cluster.members):
                continue
            if _fold_one(graph, cluster):
                progress = True

    # 折叠只换掉中间那一节，成员层还铺在原地。把每个聚合端点 tag 的成员层
    # 整层上交，链才真正变成 `原木 → 木板 → 木台阶` 三个节点。
    if rules_by_head is not None:
        endpoints = {
            endpoint
            for source, target, edge_tag in graph.edges
            if edge_tag.startswith("iso::")
            for endpoint in (source, target)
        }
        for tag in sorted(endpoints):
            graph.absorbed_members += absorb_members(graph, rules_by_head, tag)

        # 中转 tag：`tag:bamboo_blocks → tag:planks` 里的来源自己也是 tag。
        # 它的成员层同样只是一层站——把出边全指向聚合 tag 的 tag 一并吸收，
        # 否则「竹块 → 木板」会带着 4 个成员 item 留在图里。
        progress = True
        while progress:
            progress = False
            outs: dict[str, set[str]] = {}
            for source, target, _ in graph.edges:
                outs.setdefault(source, set()).add(target)
            for node in list(graph.nodes):
                if not node.startswith("tag:") or node in endpoints:
                    continue
                targets = outs.get(node, set())
                if not targets or not targets <= endpoints:
                    continue
                graph.absorbed_members += absorb_members(graph, rules_by_head, node)
                endpoints.add(node)
                progress = True

    return sum(1 for c in clusters if f"iso::{c.tag}" in {e[2] for e in graph.edges})


def _fold_one(graph: PathGraph, cluster: Cluster) -> bool:
    """折叠单个簇。返回是否真的改动了图。"""
    present = [m for m in cluster.members if m in graph.nodes]

    # 只删本簇的规则菱形（那 13 个「合成 · 工作台」）。
    # 成员节点先留着，删完再看是否变成孤立——孤立才删。
    # 这一步必须有：成员往往另有来源（挖掘掉落），全删会把那条途径也抹掉。
    doomed_rules = {f"rule::{rid}" for rid in cluster.rule_ids}

    # 同一族的规则可能已被聚合成 folder 节点（`group::<产物>::<family>/<类别>`）。
    # 那种情况下规则菱形根本不在图里，只删 rule id 会漏掉 folder，
    # 折叠边与 folder 会同时指向产物，等于什么都没省。所以一并清掉。
    doomed_groups: set[str] = set()
    for member in present:
        prefix = f"group::{member}::{cluster.family}"
        doomed_groups |= {k for k in graph.nodes if k.startswith(prefix)}
    doomed = doomed_rules | doomed_groups

    # 单前件配方在图上被压成了边（`tag:oak_logs → item:oak_planks [合成]`），
    # 没有规则节点可删。所以按「成员 + 它的来源」直接删那条边——
    # 只删这一对，成员的其它来源（挖掘掉落）保留。
    doomed_edges = {
        e for e in graph.edges
        if e[1] in cluster.members and e[0] == cluster.members[e[1]]
    }

    drawn = doomed & set(graph.nodes) | doomed_edges
    if not drawn and not present:
        return False
    removed_rules = len(drawn)

    graph.forget_nodes(doomed & set(graph.nodes))
    for edge in doomed_edges:
        graph.edge_dropped(edge)

    # 删完之后既无入边也无出边的成员就是孤立的，一并删掉。
    # 只看入边不够：成员也可能作为原料被别的规则引用。
    touched = {n for edge in graph.edges for n in edge[:2]}
    graph.forget_nodes([member for member in present if member not in touched])

    # 产物 tag 与来源 tag 都要有节点
    target_tag = cluster.tag
    source_tag = cluster.source_tag
    if target_tag not in graph.nodes:
        graph.nodes[target_tag] = {
            "sort": split_node(target_tag)[0],
            "label": f"{short(target_tag)}\\n{len(cluster.members)} 种",
        }
    if source_tag not in graph.nodes:
        graph.nodes[source_tag] = {"sort": split_node(source_tag)[0]}

    pairs = "\n".join(
        f"{short(v)} → {short(m)}" for m, v in sorted(cluster.members.items())
    )
    count = len(cluster.members)
    # 标签三段：来源类别 / 固定条件（工作台、熔炉…）/ 组数。
    # 「N 组一一对应」必须在，否则折叠会被读成「任意搭配」：
    # `oak_planks` 只能做 `oak_slab`，不是任意木板能做任意台阶。
    head = cluster.label or cluster.kind
    conditions = condition_label_text(cluster.fixed)
    first = f"{head} · {conditions}" if conditions else head
    label = f"{first}\\n{count} 组一一对应"
    key = (source_tag, target_tag, f"iso::{target_tag}")
    graph.edges[key] = (label, f"同构成簇（{count} 组，一一对应）\n{pairs}")
    # 聚合边用固定紫色：它不是某一条规则，是一批规则的合并
    graph.edge_colors[key] = ISOMORPHIC_COLOR
    graph.isomorphic += removed_rules
    return True


# ---------------------------------------------------------------- 成员层上交


def _tag_members(rules_by_head: dict[str, list[Rule]], tag: str) -> set[str]:
    """tag 的直接成员。判据与 `find_isomorphic_clusters` 里的 `raw` 一致。"""
    if not tag.startswith("tag:"):
        return set()
    return {
        rule.body[0]
        for rule in rules_by_head.get(tag, ())
        if len(rule.body) == 1
    }


def _tag_descendants(rules_by_head: dict[str, list[Rule]], tag: str) -> set[str]:
    """tag 的全部后代（含中间 tag），不含 tag 自己。"""
    seen: set[str] = set()
    stack = list(_tag_members(rules_by_head, tag))
    while stack:
        node = stack.pop()
        if node == tag or node in seen:
            continue
        seen.add(node)
        if node.startswith("tag:"):
            stack.extend(_tag_members(rules_by_head, node))
    return seen


def _leaf_members(rules_by_head: dict[str, list[Rule]], tag: str) -> set[str]:
    """tag 的叶子成员（不含中间 tag）。"""
    return {
        node for node in _tag_descendants(rules_by_head, tag) if not node.startswith("tag:")
    }


def absorb_members(
    graph: PathGraph, rules_by_head: dict[str, list[Rule]], tag: str
) -> int:
    """把 tag 的成员层整层上交到 tag，返回删除的节点数。

    ## 为什么需要这一遍

    折叠只换掉了「木台阶 ← 木板」这一节。折叠之后，`tag:item/planks` 有了
    入边，但木板层的 13 个 item、原木层的 48 个 item 与 12 个成员 tag 仍
    各自铺在原位——链还是散的，只是中间少了一层。

    要的形态是：`原木 → 木板 → 木台阶` 三个节点成链，成员整层收进节点
    标签（「48 种」），来源仍完整（外部的方块表、结构表、交易都挂到 tag 上）。

    ## 规则

    1. **外部入边重挂到 tag**：`table:blocks/oak_log → item:oak_log` 改成
       `→ tag:item/logs`。来源不变，落点从「某个成员」升到「这一层」。
    2. **层内边直接删**：`oak_log → oak_wood`、`oak_log → tag:oak_logs` 这类
       关系在整层被压掉后没有落点，而「这层有哪些形态」已由「N 种」概括。
    3. **只删画出来的部分**：层内没进图的节点不处理，避免影响 `max_nodes`
       的截断统计。

    这一遍只在有同构折叠时跑（由 `merge_isomorphic` 调用），没有折叠的图
    不会被它改动。
    """
    layer = _tag_descendants(rules_by_head, tag)
    live = {node for node in layer if node in graph.nodes}
    if not live:
        return 0

    # 1. 外部入边改挂到 tag。层内边不搬。
    for key in list(graph.edges):
        source, target, edge_tag = key
        if target not in live or source in live:
            continue
        new_key = (source, tag, edge_tag)
        if new_key in graph.edges:
            continue
        graph.edges[new_key] = graph.edges[key]
        graph.edge_colors[new_key] = graph.edge_colors.get(key, DEFAULT_EDGE_COLOR)
        if key in graph.dashed:
            graph.dashed.add(new_key)
        if key in graph.condition_edges:
            graph.condition_edges.add(new_key)

    # 2. 删掉层内的全部边与节点
    for key in [k for k in graph.edges if k[0] in live or k[1] in live]:
        graph.edge_dropped(key)
    graph.forget_nodes(live)

    # 聚合 folder 的键是 `group::<被聚合的节点>::<类别>`。两种来源要一起删：
    # 层内节点自己的 folder（`group::tag:item/oak_logs::bridge/tag`），
    # 以及 tag 自己的成员 folder（`group::tag:item/wooden_slabs::bridge/tag`）——
    # 后者的成员已被压进 tag 节点的「N 种」，留着就是一根指向虚空的线。
    doomed_groups = [
        node
        for node in graph.nodes
        if node.startswith("group::") and node.split("::", 2)[1] in (live | {tag})
    ]
    graph.forget_nodes(doomed_groups)

    # 3. 悬空的规则菱形：它的 body 成员被层删除吃掉。两种形态都要清：
    #    出边没了（菱形指向的产物被删），或入边没了（菱形的前提被删，只剩
    #    `→ head` 一条线挂在那里）。反复清到稳定——删一个会再空出一个。
    for _ in range(6):
        ins = {key[1] for key in graph.edges}
        outs = {key[0] for key in graph.edges}
        doomed = [
            node
            for node in graph.nodes
            if node.startswith("rule::") and (node not in outs or node not in ins)
        ]
        if not doomed:
            break
        graph.forget_nodes(doomed)
    graph.rules = {rule_id for rule_id in graph.rules if f"rule::{rule_id}" in graph.nodes}

    # 4. tag 自己要有标签：叶子数比「3 种成员」更能说明它盖住了什么
    leaves = len(_leaf_members(rules_by_head, tag))
    if tag not in graph.nodes:
        graph.nodes[tag] = {"sort": split_node(tag)[0]}
    graph.nodes[tag]["label"] = f"{short(tag)}\\n{leaves} 种"
    graph.nodes[tag]["tooltip"] = f"{tag}\n{leaves} 个叶子成员"
    return len(live)


# ---------------------------------------------------------------- L5 叶子桶


def bucket_leaves(graph: PathGraph, min_count: int) -> int:
    """把「同一目标、同一来源层」的多条边聚成一个计数桶，返回桶数。

    上交之后 `tag:item/logs` 会收到 48 条「某个方块 → 它」的挖掘边。逐条画
    就是一列 48 个方块节点，而它们的差别只在方块名——信息已经在聚合节点的
    「48 种」里。聚成 `方块 · 48 条`，明细进 tooltip。

    判据：

    - 同一目标、同一边标签、来源层相同（按 `source_name` 取名）
    - 条数 ≥ `min_count`
    - 不是条件边、不是环边

    被吞来源的上游改挂到桶上——`world → block ×48` 变成
    `world → [方块 · 48 条]`，世界生成这条信息不丢。
    """
    if min_count <= 0:
        return 0
    total = 0
    # 反复跑到稳定：第一遍把 13 条 `block → 目标` 收成一桶，此时模板便签
    # 还指向那 13 个方块；第二遍它们全指向桶了，才聚得起来。
    while True:
        made = _bucket_once(graph, min_count)
        if not made:
            return total
        total += made


def _bucket_once(graph: PathGraph, min_count: int) -> int:
    """做一轮桶化。返回本轮新建的桶数。"""
    buckets: dict[tuple[str, str, str], list[tuple[str, str, str]]] = {}
    for key in list(graph.edges):
        source, target, edge_tag = key
        # 组节点与省略便签不是「来源」，它们已经代表一批东西
        if source.startswith(("group::", "omitted::")):
            continue
        if source == target:
            continue
        if key in graph.condition_edges:
            continue
        label = graph.edges[key][0]
        # 环边是结构事实，不是来源；不给它做桶
        if label == "（环）":
            continue
        layer = source_name(source, graph.nodes.get(source, {}).get("category"))
        buckets.setdefault((target, label, layer), []).append(key)

    made = 0
    for (target, label, layer), keys in sorted(buckets.items()):
        if len(keys) < min_count:
            continue
        # key 用计数编号，不用目标名：桶可以套桶（模板便签指向方块桶），
        # 拿目标名拼会得到 `bucket::bucket::…` 这种又长又难读的 key。
        key = f"bucket::{graph.buckets + 1}"
        tips = "\n".join(f"{short(src)} → {short(target)}" for src, _, _ in keys)
        graph.nodes[key] = {
            "sort": "bucket",
            "label": f"{layer} · {len(keys)} 条" + (f"\\n{label}" if label else ""),
            "tooltip": f"{layer}（{len(keys)} 条）\n{tips}",
        }
        graph.buckets += 1

        # 桶 → 目标
        graph.edges[(key, target, key)] = (label, f"{len(keys)} 条同层来源")
        graph.edge_colors[(key, target, key)] = graph.edge_colors.get(
            keys[0], DEFAULT_EDGE_COLOR
        )

        # 被吞来源的上游改挂到桶上；同标签的多条合成一条
        for source, _, _ in keys:
            for upstream in [k for k in graph.edges if k[1] == source]:
                up_source, _, _ = upstream
                up_label, up_tip = graph.edges[upstream]
                up_key = (up_source, key, f"bucket::{up_label}")
                if up_key in graph.edges:
                    continue
                graph.edges[up_key] = (up_label, up_tip)
                graph.edge_colors[up_key] = graph.edge_colors.get(
                    upstream, DEFAULT_EDGE_COLOR
                )
            for stale in [k for k in graph.edges if k[0] == source or k[1] == source]:
                graph.edge_dropped(stale)
            graph.forget_nodes([source])
        made += 1

    if made:
        touched = {node for edge in graph.edges for node in edge[:2]}
        orphans = [
            node
            for node in graph.nodes
            if node not in touched and node.startswith(("rule::", "group::", "templates::"))
        ]
        graph.forget_nodes(orphans)
        graph.rules = {r for r in graph.rules if f"rule::{r}" in graph.nodes}
    return made


# ---------------------------------------------------------------- L4 表中转


# ---------------------------------------------------------------- 起点吸收


# 不是「来源」的内部节点。吸收起点时它们不算入边，删的时候一起清掉。
_NON_SOURCE_PREFIXES = (
    "rule::",
    "group::",
    "bucket::",
    "omitted::",
    "blocked::",
    "templates::",
)


def absorb_roots(graph: PathGraph, *, keep: bool = False) -> int:
    """把所有「起点 → 产物」的边收进产物节点的标签，返回吸收的节点数。

    ## 为什么

    `world:overworld --[生成]--> block:grass_block` 这样的边不携带分支信息：
    每个方块都由世界生成，画出来就是一根从同一个椭圆射向几十个节点的星形，
    既占版面又读不出「这个方块是怎么来的」。把起点压进节点标签
    （`草方块 / 主世界生成`）之后，读者一眼看到的是「这个方块在世界里生成」，
    而不是「这里有个叫世界的节点，它连过来一条线」。

    与 `station:`（工作台）同一处理：**不产出分支的东西不画成节点**。

    ## 只收直接指向产物的边

    指向 `rule::` 菱形的起点边一律不动：那是 AND 的一员（交易 = 假设 + 付款物），
    删掉会让整条规则失效。判据是 target 的前缀，不是边的标签。

    ## 分组吃掉的起点要补回来

    组内规则全是「单前件 = 全局起点」时，folder 就是「N 条起点规则」的壳：
    起点边根本不在图上，folder 直接连产物。这类情形由 `_emit_group` 记进
    `pending_roots`，在这里一并吸收——否则 folder 会变成无源节点。

    ## 没有入边的战利品表

    深度预算用尽时 `Builder` 会建 `table:` 节点但不往上走，于是表的来源
    （`assume:structure_loot`）根本没画，表成了没头没尾的椭圆。它不是「来源」
    而是「从哪拿」——和起点一样收进产物标签（`木桶 · abandoned_camp_barrel`）。

    ## 附带吸收模板便签

    `bindings/template_block` 规则的 `templates` 便签是「这条规则的出处」，
    它挂在产物上只是为了指向。吸收起点时把结构名并进标签
    （`结构放置·village`），便签一并删掉——留着会变成一根指向已删节点的虚线。
    """
    if keep:
        return 0

    # target → [(边 key, origin 串)]
    per_target: dict[str, list[tuple[tuple[str, str, str], str]]] = {}
    for key in list(graph.edges):
        source, target, _ = key
        if target.startswith(_NON_SOURCE_PREFIXES):
            continue
        try:
            sort = split_node(source)[0]
        except ValueError:
            continue
        if sort not in ROOT_SORTS:
            continue

        label = graph.edges[key][0]
        templates = tuple(
            # `meta.templates` 存的是完整路径，结构名要取剥掉
            # `data/<ns>/structure/` 前缀后的首段。
            short_template(path)
            for other in graph.edges
            if other[1] == target and other[0].startswith("templates::")
            for path in _template_paths(graph, other[0])
        )
        per_target.setdefault(target, []).append(
            (key, root_source_label(source, label, templates))
        )

    # 分组时被吃掉的上游：folder 自己就是「N 条起点规则」的壳，实
    # 际的来源是那个起点。不并进来，folder 会变成无源节点。
    for target, pairs in graph.pending_roots.items():
        if target not in graph.nodes:
            continue
        for source, label in pairs:
            per_target.setdefault(target, []).append(
                (None, root_source_label(source, label))
            )

    # 没有入边的表：深度截断让来源没画出来，表节点于是悬空。
    # 它仍然表达了「这东西从哪个表里出」，所以收进产物标签而不是删掉。
    contained = {k[1] for k in graph.edges}
    orphan_tables = [
        node
        for node in graph.nodes
        if node.startswith("table:") and node not in contained
    ]
    for node in orphan_tables:
        targets = [k[1] for k in graph.edges if k[0] == node]
        # 指向 `rule::` 菱形时不能收：菱形是 AND 的一员，吸走会让规则失去
        # 名字，图上只剩一个说不清道不明的菱形。这类保留节点。
        if not targets or any(t.startswith(_NON_SOURCE_PREFIXES) for t in targets):
            continue
        label = _table_label(node)
        for target in targets:
            per_target.setdefault(target, []).append((None, label))
        for key in [k for k in graph.edges if k[0] == node]:
            graph.edge_dropped(key)
        graph.forget_nodes([node])

    absorbed = 0
    for target, items in per_target.items():
        # 同一种来源会出现多次（`生成` 有 7 条规则），标签里只写一次
        origins: list[str] = []
        for _, origin in items:
            if origin not in origins:
                origins.append(origin)
        shown = origins[:3]
        if len(origins) > len(shown):
            shown.append(f"等 {len(origins)} 种")

        info = graph.nodes.setdefault(target, {"sort": split_node(target)[0]})
        base = info.get("label") or short(target)
        info["label"] = f"{base}\\n{stacked(shown)}"
        info["origin"] = " · ".join(origins)
        info["origin_tooltip"] = "\n".join(
            graph.edges[key][1] for key, _ in items if key and graph.edges.get(key)
        )

        for key, _ in items:
            if key is not None:
                graph.edge_dropped(key)
        # 结构名已进标签，模板便签就没有指向对象了
        stale_templates = [
            other[0]
            for other in graph.edges
            if other[1] == target and other[0].startswith("templates::")
        ]
        for other in [k for k in graph.edges if k[0] in stale_templates]:
            graph.edge_dropped(other)
        graph.forget_nodes(stale_templates)
        absorbed += 1

    # 起点节点若不再连任何东西，就该消失——它已经写进各个节点的标签里了。
    # 判据是端点类型而不是节点上的标记：起点节点由 `_value` 统一创建，
    # 没有单独的 `root` 字段可依赖。
    touched = {n for key in graph.edges for n in key[:2]}
    dead = []
    for node in graph.nodes:
        if node in touched or node.startswith(_NON_SOURCE_PREFIXES):
            continue
        try:
            sort = split_node(node)[0]
        except ValueError:
            continue
        if sort in ROOT_SORTS:
            dead.append(node)
    graph.forget_nodes(dead)
    graph.absorbed_roots = absorbed
    return absorbed


def _template_paths(graph: PathGraph, key: str) -> list[str]:
    """从模板便签的 tooltip 里取回模板路径（便签的 label 已被截断）。"""
    info = graph.nodes.get(key) or {}
    return [line for line in (info.get("tooltip") or "").splitlines() if line]


def table_parts(node: str) -> tuple[str, str, str]:
    """`table:minecraft:chests/trial_chambers/x` →
    (`宝箱`, `trial_chambers/x`, `chests/trial_chambers/x`)。

    只有目录首段（`宝箱` / `陶罐` / `玩法`）汉化，表名保持原名：表名有几千个
    且随版本增减，译名表必然不全，不全就是中英混排。原名还能直接对照
    数据包路径查证。汉化边界见 `style.py`。

    三个调用点（标签命名、假设表改名、压表时的重名判断）都从这里取，
    免得同一条路径拆分规则写三份。
    """
    ident = node.split(":", 1)[1]
    _, _, path = ident.partition(":")
    head, _, rest = path.partition("/")
    return TABLE_KIND.get(head, head or "战利品"), (rest or head), path


def _table_label(node: str) -> str:
    """表节点的可读名：`宝箱 · trial_chambers/intersection`。"""
    kind, rest, _ = table_parts(node)
    return f"{kind} · {rest}"


def name_assumption_tables(graph: PathGraph) -> int:
    """把「来源于假设的表」改名，并把假设节点吸收进标签。

    `assume:structure_loot --> table:chests/trial_chambers/reward_ominous_rare`
    里的假设是全局前提（「结构里的箱子能开」），不是具体来源；真正的来源是表名。
    压成边会得到「结构战利品(reward_ominous_rare)」这种既长又不好读的标签。

    所以反过来：**保留表节点**，把假设写进标签，并删掉那条无信息量的入边。
    得到 `宝箱 · reward_ominous_rare`，这才是人话。

    只对「唯一入边且来自 assume」的表生效。有多个入边的表保留原有结构。
    """
    ins: dict[str, list[tuple[str, str, str]]] = {}
    for source, target, tag in graph.edges:
        ins.setdefault(target, []).append((source, target, tag))

    renamed = 0
    for node in [k for k in graph.nodes if k.startswith("table:")]:
        incoming = ins.get(node, [])
        if len(incoming) != 1:
            continue
        source, _, tag = incoming[0]
        if not source.startswith("assume:"):
            continue

        graph.nodes[node]["label"] = _table_label(node)
        graph.nodes[node]["tooltip"] = f"{node}\n前提：{source}"

        graph.edge_dropped((source, node, tag))
        graph.absorbed_assumptions += 1
        renamed += 1
    return renamed


def collapse_tables(graph: PathGraph) -> int:
    """把 `table:` 中介节点压进边，返回压缩的节点数。

    `block:X --[战利品表]--> table:blocks/X --[挖掘方块]--> item:Y` 里的
    `table:blocks/X` 不携带新信息——名字就是来源方块名。留着只是让链多一节。

    判据收得很窄，只动 `table:`，且**只要求一条入边**：

    - 只有一条入边：这个表归属于唯一一个来源（某个方块、某个结构、某个实体），
      于是每条 `来源 → 表 → 产物` 都能直接写成 `来源 → 产物`
    - 表有多条出边是常态（一张方块表同时掉物品和「精准采集才掉的方块」），
      把它们各自压成一条边，信息不丢
    - 有多个入边时保留节点：那是真的多对一汇合点，压掉会伪造出交叉关系

    表名末段与来源名末段相同时（`blocks/emerald_ore` ← `block:emerald_ore`）
    标签只取出边标签；不同时（`chests/ancient_city` ← `assume:structure_loot`）
    把表名写进标签，因为那是唯一信息源。

    不动 `block:` / `entity:`：它们是分析对象，压掉就看不出「挖的是哪个方块」。
    """
    ins: dict[str, list[tuple[str, str]]] = {}
    outs: dict[str, list[tuple[str, str]]] = {}
    for source, target, tag in graph.edges:
        outs.setdefault(source, []).append((target, tag))
        ins.setdefault(target, []).append((source, tag))

    removed = 0
    for node in [k for k in graph.nodes if k.startswith("table:")]:
        incoming = ins.get(node, [])
        outgoing = outs.get(node, [])
        # 入边可能只有一条规则、但被多条边重复登记，按来源去重后再判
        sources = {src for src, _ in incoming}
        if len(sources) != 1 or not outgoing:
            continue
        source = next(iter(sources))
        if source == node or source.startswith("group::"):
            continue

        in_edge = next(((s, t, g) for s, t, g in graph.edges if s == source and t == node), None)
        if in_edge is None:
            continue
        _, in_tip = graph.edges[in_edge]

        # 表名末段（`blocks/emerald_ore` → `emerald_ore`）与来源末段相同即信息重复。
        # 来源要剥两层：`block:minecraft:emerald_ore` → `emerald_ore`。
        _, _, table_path = table_parts(node)
        table_tail = table_path.split("/", 1)[-1]
        source_tail = short(source).split(":", 1)[-1].split("/", 1)[-1]
        name_is_redundant = table_tail == source_tail
        short_name = table_path.rsplit("/", 1)[-1]

        for target, tag in outgoing:
            out_edge = (node, target, tag)
            out_label, out_tip = graph.edges[out_edge]
            color = graph.edge_colors.get(out_edge, DEFAULT_EDGE_COLOR)
            if name_is_redundant:
                label = out_label
            elif source.startswith("assume:") or source.startswith("world:"):
                # 假设没有具体名字，表名是唯一信息源；用与孤儿表一致的
                # `类别 · 路径` 写法，不要 `挖掘方块(corridor)` 这种丢层级的形式。
                label = _table_label(node)
            else:
                label = f"{out_label}({short_name})" if out_label else short_name
            label = label.strip(" ·")

            # 不同的表压到同一条 `来源 → 产物` 上时不能共用一个 key：
            # `item:emerald_block` 同时从试炼密室的交叉口箱、奖励箱、陶罐掉落，
            # 三条边会互相覆盖，最后只剩一个表名。表名进 tag，各自成边。
            key = (source, target, f"{tag}|{node}")
            graph.edges[key] = (label, f"{in_tip}\n{out_tip}")
            graph.edge_colors[key] = color

        for target, tag in outgoing:
            graph.edge_dropped((node, target, tag))
        graph.edge_dropped(in_edge)
        graph.forget_nodes([node])
        removed += 1

    return removed
