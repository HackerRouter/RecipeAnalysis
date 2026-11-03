"""实体桥接：实体从哪来、能做什么。

两张机制表各自对应一个函数，改一条知识就改这里的一处：

- `entity_source_rules` 读 `knowledge/maps/mechanism/entity_sources`
- `entity_behaviour_rules` 读 `knowledge/maps/mechanism/entity_behaviour`
"""

from __future__ import annotations

from collections import Counter

from ..nodes import Rule, node, split_node

__all__ = ["entity_behaviour_rules", "entity_source_rules"]


def entity_source_rules(sources: dict[str, dict]) -> tuple[list[Rule], dict[str, int]]:
    """不来自世界生成的实体：`entity:X ←spawns← 它成立的依据`。

    两类（`knowledge/maps/mechanism/entity_sources.json` 的 `kind`）：

    | kind | 例子 | body |
    |---|---|---|
    | `summon` | 凋灵：玩家摆 3 个头 + 4 块灵魂沙 | 摆它要用的东西 |
    | `dimension` | 末影龙：固定在末地 | `assume:end` |

    两者都不是世界生成事实能给的：凋灵不会自然生成、末影龙不经 biome spawner。
    成员尽量走 tag（`wither_summon_base_blocks` 这类），不在这里枚举具体方块。

    返回 `(规则, 未解析)`：`requires` 出现非法节点、或表项缺字段，都记进后一项。
    """
    rules: list[Rule] = []
    problems: Counter = Counter()

    for entity, spec in sorted(sources.items()):
        if not isinstance(spec, dict):
            problems[f"{entity}:spec_invalid"] += 1
            continue
        kind = spec.get("kind")
        if kind not in ("summon", "dimension"):
            problems[f"{entity}:unknown_kind:{kind}"] += 1
            continue
        requires = spec.get("requires")
        if not isinstance(requires, list) or not requires:
            problems[f"{entity}:no_requires"] += 1
            continue
        body: list[str] = []
        broken = False
        for node_id in requires:
            if not isinstance(node_id, str):
                broken = True
                break
            try:
                split_node(node_id)
            except ValueError:
                broken = True
                break
            body.append(node_id)
        if broken:
            problems[f"{entity}:bad_node"] += 1
            continue

        rules.append(
            Rule(
                id=f"bridge:entity_source:{entity}",
                head=entity if entity.startswith("entity:") else node("entity", entity),
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


def entity_behaviour_rules(behaviours: dict[str, dict]) -> tuple[list[Rule], dict[str, int]]:
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
    由人核对一次，之后编译期只需检查节点合法性。

    `actor` / `inputs` 可以是任何排序的节点：
    `tadpole` 的 actor 是 `block:minecraft:frogspawn`（孵化），
    `player_head` 的 actor 是 `assume:player`（玩家自身）。

    返回 `(规则, 未解析)`。
    """
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
        for node_id in [actor, *inputs]:
            if not isinstance(node_id, str):
                broken = True
                break
            try:
                split_node(node_id)
            except ValueError:
                broken = True
                break
            body_nodes.append(node_id)
        if broken:
            problems[f"{name}:bad_node"] += 1
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
