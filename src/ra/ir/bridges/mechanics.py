"""机制桥接：变换约定与表的产出者。

## 表的产出者：两路，优先事实

优先用 `holds` 事实；没有时退回命名约定，并检查覆盖率。

- `holds` 事实来自 `code_link`（`dropsLike` / `wallVariant`）与 `loot_alias`
- 命名约定是 `loot_table/blocks/<方块名>.json` → `block:<方块名>`

约定覆盖率必须打印：若大量表按约定挂到了不存在的方块上，说明该版的目录语义变了。

## 依据

- `convention_transform_rules` 读 `knowledge/maps/mechanism/transform_conventions`
- `table_provider_rules` 读 `knowledge/maps/mechanism/table_providers`
"""

from __future__ import annotations

from collections import Counter

from ...facts import Fact
from ..nodes import Rule, node

__all__ = ["convention_transform_rules", "table_provider_rules"]


def convention_transform_rules(
    block_ids: set[str], conventions: dict[str, dict]
) -> tuple[list[Rule], dict[str, int]]:
    """按命名约定补变换：`block:<head> ← block:<body>, <前提>`。

    变换事实只记「玩家用工具作用于方块」，而固化、脱水、珊瑚死亡这类是方块自身的
    物理行为，没有工具、也没有事实。允许退回命名约定，前提是**检查覆盖率**。

    每条约定声明：

    | 字段 | 含义 |
    |---|---|
    | `match_prefix` / `match_suffix` | 扫描侧方块名的前缀或后缀，`{stem}` 是去掉它之后的余部 |
    | `stem_contains` | 余部必须包含的子串，用来收窄过宽的词缀（见 `coral_death`） |
    | `head` | 目标名模板，`{stem}` 占位 |
    | `body` | 源名模板，`{stem}` 占位 |
    | `requires` | 该变换的附加前提节点 |
    | `basis` | 一行依据 |

    配对不上的一律记 `miss`，不静默缩小适用范围。
    """
    rules: list[Rule] = []
    stats: Counter = Counter()

    for name, spec in conventions.items():
        if not isinstance(spec, dict):
            stats[f"{name}:spec_invalid"] += 1
            continue
        head_tpl = spec.get("head")
        body_tpl = spec.get("body")
        prefix = spec.get("match_prefix")
        suffix = spec.get("match_suffix")
        contains = spec.get("stem_contains")
        if not isinstance(head_tpl, str) or not isinstance(body_tpl, str):
            stats[f"{name}:spec_invalid"] += 1
            continue
        if isinstance(prefix, str) and prefix:
            match = ("prefix", prefix)
        elif isinstance(suffix, str) and suffix:
            match = ("suffix", suffix)
        else:
            # 两侧都空会命中整个注册表，那不是约定
            stats[f"{name}:spec_invalid"] += 1
            continue

        requires = tuple(
            item for item in (spec.get("requires") or []) if isinstance(item, str)
        )
        for ident in sorted(block_ids):
            namespace, _, path = ident.partition(":")
            pattern, affix = match
            if pattern == "prefix":
                if not path.startswith(affix):
                    continue
                stem = path[len(affix) :]
            else:
                if not path.endswith(affix):
                    continue
                stem = path[: -len(affix)]
            if not stem:
                stats[f"{name}:miss"] += 1
                continue
            if isinstance(contains, str) and contains and contains not in stem:
                stats[f"{name}:filtered"] += 1
                continue
            stats[f"{name}:hit"] += 1
            target = f"{namespace}:{head_tpl.format(stem=stem)}"
            source = f"{namespace}:{body_tpl.format(stem=stem)}"
            if target not in block_ids or source not in block_ids:
                stats[f"{name}:miss"] += 1
                continue
            rules.append(
                Rule(
                    id=f"bridge:convention:{name}:{ident}",
                    head=node("block", target),
                    body=(node("block", source), *requires),
                    kind="transmutes",
                    family="bridge/convention",
                    meta={
                        "convention": name,
                        "basis": spec.get("basis", ""),
                    },
                )
            )
            stats[f"{name}:paired"] += 1

    return rules, {key: int(value) for key, value in stats.items()}


def table_provider_rules(
    loot_facts: list[Fact],
    holds_facts: list[Rule],
    block_ids: set[str],
    entity_ids: set[str],
    providers: dict[str, dict],
) -> tuple[list[Rule], dict[str, int]]:
    """把战利品表挂到它的产出者上。

    `holds` 事实（来自 code_link 的 alias/借用）**始终优先**：已被事实覆盖的表
    不再走目录约定。这就是桥接的取值顺序。

    其余表按 `knowledge/maps/mechanism/table_providers.json` 的目录映射接：

    | kind | 产出者 |
    |---|---|
    | `block` | `block:<路径>`，名字须在 block 注册表 |
    | `entity` | `entity:<首段>`，名字须在 entity 注册表 |
    | `assume` | 给定的假设节点 |
    | `holds_only` | 不接（等事实） |

    两种 kind 都可带 `requires`：触发该表还得有这些东西（剪取表要剪刀）。
    前置直接进 body——没有工具就触发不了，与「表属于谁」同属硬条件。

    名字对不上注册表就记 `convention_miss`，不静默丢弃。
    """
    stats: Counter = Counter()

    covered: set[str] = set()
    rules: list[Rule] = []
    for rule in holds_facts:
        if rule.head.startswith("table:"):
            covered.add(rule.head)
            rules.append(rule)
            stats["from_fact"] += 1

    for fact in loot_facts:
        payload = fact.payload
        table_id = payload.get("table")
        if not isinstance(table_id, str):
            continue
        head = node("table", table_id)
        if head in covered:
            continue

        namespace, _, path = table_id.partition(":")
        segments = path.split("/")
        if not segments or not segments[0]:
            stats["no_provider"] += 1
            continue

        # 最长前缀匹配：先试完整路径（`spawners/ominous`），再逐段退回首段（`spawners`）。
        # 只按首段匹配不够——同一个首段下可以有普通与不祥两套前提不同的装置。
        spec = None
        for take in range(len(segments), 0, -1):
            candidate = providers.get("/".join(segments[:take]))
            if isinstance(candidate, dict):
                spec = candidate
                break
        if not isinstance(spec, dict):
            stats["no_provider"] += 1
            continue

        kind = spec.get("kind")
        stats[f"kind:{kind}"] += 1

        requires = tuple(
            item for item in (spec.get("requires") or []) if isinstance(item, str)
        )

        if kind == "holds_only":
            # 该目录的表只能由事实挂，等 code_link，不做约定
            stats["awaiting_fact"] += 1
            continue

        if kind == "assume":
            target = spec.get("node")
            if not isinstance(target, str):
                stats["spec_invalid"] += 1
                continue
            rules.append(
                Rule(
                    id=f"bridge:table:{table_id}",
                    head=head,
                    body=(target, *requires),
                    kind="holds",
                    family="bridge/table",
                    meta={"basis": spec.get("basis", "")},
                    prov=fact.prov,
                )
            )
            stats["assume"] += 1
            continue

        if kind == "block":
            if len(segments) < 2:
                stats["spec_invalid"] += 1
                continue
            full = f"{namespace}:{segments[-1]}"
            if full not in block_ids:
                stats["convention_miss"] += 1
                continue
            body = node("block", full)
        elif kind == "entity":
            full = f"{namespace}:{segments[1]}"
            if full not in entity_ids:
                stats["convention_miss"] += 1
                continue
            body = node("entity", full)
        else:
            stats["spec_invalid"] += 1
            continue

        rules.append(
            Rule(
                id=f"bridge:table:{table_id}",
                head=head,
                body=(body, *requires),
                kind="holds",
                family="bridge/table",
                meta={"basis": f"目录约定 {segments[0]}/"},
                prov=fact.prov,
            )
        )
        stats["convention"] += 1

    return rules, {key: int(value) for key, value in stats.items()}
