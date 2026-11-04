"""实体桥接：实体从哪来、能做什么。

两张机制表各自对应一个函数，改一条知识就改这里的一处：

- `entity_source_rules` 读 `knowledge/maps/mechanism/entity_sources`
- `entity_behaviour_rules` 读 `knowledge/maps/mechanism/entity_behaviour`

## 存在性对账

知识表是全版本共用的一份文件，条目不带版本条件；资源 id 却随版本增删。
不做对账，条目会在没有该内容的版本上照样编成规则，于是图里凭空多出节点：

- 结论节点不存在 → 判 false，污染节点与状态统计；
- 前提若是 `world:` / `assume:` 这类版本无关节点，规则还恒真，
  该版本根本没有的方块会被判为可得。

对账按排序分两类：`item` / `block` / `entity` 查该版本的注册表，
其余排序（`tag`、`table`、`station`、`tool`、`enchant`、`structure`、`world`、
`assume`）由各自的事实或约定保证，不在此判。
"""

from __future__ import annotations

from collections import Counter

from ..nodes import Rule, node, split_node

__all__ = ["entity_behaviour_rules", "entity_source_rules"]

# 需要对账的节点排序。调用方须为每个排序给出该版本存在的 id 集合。
CHECKED_SORTS = ("item", "block", "entity")


def _require_registries(known: dict[str, set[str]]) -> None:
    missing = [sort for sort in CHECKED_SORTS if sort not in known]
    if missing:
        raise ValueError(f"缺少注册表集合：{missing}，实体类知识表无法对账")


def _known(known: dict[str, set[str]], node_id: str) -> bool:
    """节点在当前版本是否确实存在。不参与对账的排序一律放行。"""
    sort, ident = split_node(node_id)
    if sort not in CHECKED_SORTS:
        return True
    return ident in known[sort]


def entity_source_rules(
    sources: dict[str, dict], known: dict[str, set[str]]
) -> tuple[list[Rule], dict[str, int]]:
    """不来自世界生成的实体：`entity:X ←spawns← 它成立的依据`。

    四类（`knowledge/maps/mechanism/entity_sources.json` 的 `kind`）：

    | kind | 例子 | body |
    |---|---|---|
    | `summon` | 凋灵：玩家摆 3 个头 + 4 块灵魂沙 | 摆它要用的东西 |
    | `dimension` | 末影龙：固定在末地 | `assume:end` |
    | `breed` | 骡：马与驴繁殖 | 两个亲本实体 |
    | `event` | 流浪商人、行商羊驼：生成器放置 | 触发者实体或前提假设 |

    四者都不是世界生成事实能给的：凋灵不会自然生成、末影龙不经 biome spawner、
    骡与行商羊驼不由任何生物群系的刷怪表生成。成员尽量走 tag（`wither_summon_base_blocks`
    这类），不在这里枚举具体方块。

    实体本身或某个 `requires` 在该版本不存在时整条不产：`requires` 是必要条件，
    缺一个机制就不成立，留下规则只会让 head 恒假。

    返回 `(规则, 未解析)`：`requires` 出现非法节点、或表项缺字段，都记进后一项。
    """
    _require_registries(known)
    rules: list[Rule] = []
    problems: Counter = Counter()

    for entity, spec in sorted(sources.items()):
        if not isinstance(spec, dict):
            problems[f"{entity}:spec_invalid"] += 1
            continue
        kind = spec.get("kind")
        if kind not in ("summon", "dimension", "breed", "event"):
            problems[f"{entity}:unknown_kind:{kind}"] += 1
            continue
        requires = spec.get("requires")
        if not isinstance(requires, list) or not requires:
            problems[f"{entity}:no_requires"] += 1
            continue

        head = entity if entity.startswith("entity:") else node("entity", entity)
        if not _known(known, head):
            problems[f"{entity}:unknown_entity"] += 1
            continue

        body: list[str] = []
        broken = False
        absent = False
        for node_id in requires:
            if not isinstance(node_id, str):
                broken = True
                break
            try:
                split_node(node_id)
            except ValueError:
                broken = True
                break
            if not _known(known, node_id):
                absent = True
                break
            body.append(node_id)
        if broken:
            problems[f"{entity}:bad_node"] += 1
            continue
        if absent:
            problems[f"{entity}:unknown_node"] += 1
            continue

        rules.append(
            Rule(
                id=f"bridge:entity_source:{entity}",
                head=head,
                body=tuple(body),
                kind="spawns",
                family="bridge/entity_source",
                meta={
                    "source_kind": kind,
                    "pattern": spec.get("pattern", ""),
                    "basis": spec.get("basis", ""),
                },
            )
        )

    return rules, {key: int(value) for key, value in problems.items()}


def entity_behaviour_rules(
    behaviours: dict[str, dict], known: dict[str, set[str]]
) -> tuple[list[Rule], dict[str, int]]:
    """实体行为产出：`产出 ←yield← 行为主体 + 消耗品`。

    `knowledge/maps/mechanism/entity_behaviour.json` 每条声明「谁做什么，得到什么」：

    ```
    item:minecraft:dragon_breath  ←yield←  entity:minecraft:ender_dragon
                                            item:minecraft:glass_bottle
    ```

    **为什么不写成 idiom**：这些产出一律没有固定代码形态。同样是「实体产出」，
    龙蛋走 `setBlockAndUpdate`、龙息走 `turnBottleIntoItem`、海龟蛋走
    `setValue(TurtleEggBlock.EGGS, ...)`、玩家头走战利品表回调、
    青蛙卵走 `Activity` 的某一步。写一个 idiom 只能抓到其中一两种，
    而抓漏时不报错。

    因此用声明式：每条给出 `evidence`（代码行或数据包路径），
    由人核对一次，之后编译期检查节点合法性与存在性。

    `actor` / `inputs` 可以是任何排序的节点：
    `tadpole` 的 actor 是 `block:minecraft:frogspawn`（孵化），
    `player_head` 的 actor 是 `assume:player`（玩家自身）。

    对账的粒度不对称，因为前提与结论的性质不同：

    - `actor` / `inputs` 是该版本不存在的东西 → 机制不存在，整条不产；
    - 某个 `produces` 该版本不存在 → 只剔除该结论，同一机制其余的产物照产。

    返回 `(规则, 未解析)`。
    """
    _require_registries(known)
    rules: list[Rule] = []
    problems: Counter = Counter()

    for name, spec in sorted(behaviours.items()):
        if not isinstance(spec, dict):
            problems[f"{name}:spec_invalid"] += 1
            continue
        produces = spec.get("produces")
        if not isinstance(produces, list) or not produces:
            problems[f"{name}:no_produces"] += 1
            continue
        actor = spec.get("actor")
        inputs = spec.get("inputs") or []
        if not isinstance(actor, str) or not isinstance(inputs, list):
            problems[f"{name}:bad_actor_or_inputs"] += 1
            continue

        body_nodes: list[str] = []
        broken = False
        absent = False
        for node_id in [actor, *inputs]:
            if not isinstance(node_id, str):
                broken = True
                break
            try:
                split_node(node_id)
            except ValueError:
                broken = True
                break
            if not _known(known, node_id):
                absent = True
                break
            body_nodes.append(node_id)
        if broken:
            problems[f"{name}:bad_node"] += 1
            continue
        if absent:
            problems[f"{name}:unknown_node"] += 1
            continue

        for index, head in enumerate(produces):
            if not isinstance(head, str):
                problems[f"{name}:bad_produces"] += 1
                break
            try:
                split_node(head)
            except ValueError:
                problems[f"{name}:bad_produces"] += 1
                break
            if not _known(known, head):
                problems[f"{name}:unknown_produce"] += 1
                continue
            rules.append(
                Rule(
                    id=f"bridge:behaviour:{name}:{index}",
                    head=head,
                    body=tuple(body_nodes),
                    kind="yield",
                    family="bridge/entity_behaviour",
                    meta={
                        "behaviour": name,
                        "actor": actor,
                        "basis": spec.get("basis", ""),
                        "evidence": spec.get("evidence", ""),
                    },
                )
            )

    return rules, {key: int(value) for key, value in problems.items()}
