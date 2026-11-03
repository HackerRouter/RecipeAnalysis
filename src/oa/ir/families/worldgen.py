"""世界生成 → `seeds` 规则。

存在性语义：世界无限，只要生成条件非空，足够大的范围内必然出现。
**定义了就是有**——不判群系可否抵达、不算投放间距、不跑实测。

所以这里的规则形状很简单：

```
block:minecraft:diamond_ore        ←seeds←  world:minecraft:overworld
structure:minecraft:end_city       ←seeds←  world:minecraft:overworld
entity:minecraft:zombie            ←seeds←  world:minecraft:overworld
```

`world:*` 由假设清单播种为真，因此这些 `seeds` 规则会让对应节点直接为真。

## `slot` 不可靠，用注册表锚定

事实里的 `references[].slot` 由适配器给出，只有 `block` / `structure` / `feature` /
`template` / `entity` 几种。「`entity`」不是「实体」的意思，而是**兜底**——
一切无法归类的引用都落在这里。实测 `noise_settings` 的**默认方块**（`minecraft:stone`）
被标成 `slot=entity`，若只信 slot，地表方块就全部不可达，进而整条掉落链断掉。

所以判据改成：**引用 ID 命中哪个注册表就按哪个排序**。

| 引用 ID 在 | 排序 |
|---|---|
| block 注册表 | `block` |
| entity_type 注册表 | `entity` |
| `worldgen_kind=structure_set` 且 slot=structure | `structure` |

这套判据与阶段一 probe 的原则一致：用注册表当锚点，不靠字段名猜。

## 维度归属

本期不细分维度：所有生成物都挂 `world:minecraft:overworld`。
理由是存在性语义下三维度都可达（`assume:nether` / `assume:end` 为真），
细分只会增加事实需求而不改变结论。将来要区分时从 biome 事实反查即可，
不需要改本模块的规则形状。
"""

from __future__ import annotations

from collections import Counter

from ...facts import Fact
from ..nodes import Rule, node, tag_node
from ..tags import TagMembers

FAMILY = "worldgen"

# 本期统一的维度节点
DEFAULT_WORLD = "world:minecraft:overworld"


class WorldgenCompileResult:
    def __init__(self) -> None:
        self.rules: list[Rule] = []
        self.slot_counts: Counter = Counter()
        self.anchored_by_registry: Counter = Counter()
        self.unresolved_refs: Counter = Counter()


def compile_worldgen(
    facts: list[Fact],
    block_ids: set[str],
    entity_ids: set[str],
    tags: TagMembers | None = None,
) -> WorldgenCompileResult:
    """把世界生成事实编译成 `seeds` 规则。

    `block_ids` / `entity_ids` 是注册表条目全集，用于锚定引用排序。
    `tags` 用于展开「从标签里随机选一个放置」的引用，见 `_tag_expansion`。
    """
    result = WorldgenCompileResult()
    members = tags if tags is not None else TagMembers([])

    for fact in facts:
        payload = fact.payload
        kind = payload.get("worldgen_kind")
        ident = payload.get("id")
        if not isinstance(ident, str):
            continue
        source = f"{kind}/{ident.rsplit('/', 1)[-1]}"

        for index, ref in enumerate(payload.get("references") or []):
            if not isinstance(ref, dict):
                continue
            slot = ref.get("slot")
            target = ref.get("id")
            result.slot_counts[slot] += 1
            if not isinstance(target, str):
                continue

            if slot == "tag":
                expanded = _tag_expansion(fact, index, target, members)
                if expanded is None:
                    result.unresolved_refs["tag"] += 1
                else:
                    result.rules.extend(expanded)
                continue

            sort: str | None = None
            if slot == "structure":
                sort = "structure"
            elif target in block_ids:
                sort = "block"
                if slot != "block":
                    result.anchored_by_registry[f"{slot}→block"] += 1
            elif target in entity_ids:
                sort = "entity"
                if slot != "entity":
                    result.anchored_by_registry[f"{slot}→entity"] += 1
            else:
                result.unresolved_refs[slot] += 1
                continue

            result.rules.append(
                Rule(
                    id=f"worldgen:{fact.prov.file}#{index}",
                    head=node(sort, target),
                    body=(DEFAULT_WORLD,),
                    kind="seeds",
                    family=FAMILY,
                    meta={"source": source, "worldgen_kind": kind, "slot": slot},
                    prov=fact.prov,
                )
            )

    return result


def _tag_expansion(
    fact: Fact,
    index: int,
    tag_id: str,
    members: TagMembers,
) -> list[Rule] | None:
    """「从标签里随机选一个放置」→ 标签节点为真 + 每个成员各一条 OR 规则。

    形状：

    ```
    tag:block/minecraft:corals  ←seeds←   world:minecraft:overworld
    block:minecraft:brain_coral ←implies← tag:block/minecraft:corals
    ...（其余成员同理）
    ```

    **为什么成员全部为真而不是只取一个**：存在性语义——世界无限，
    只要生成条件非空就必然出现足够多次。随机选择意味着每个成员的被选概率
    非零，于是每个成员都能在某处生成。这与「定义了就是有」是同一条语义。

    反过来，如果标签不存在或没有可解析的成员，返回 `None`，由调用方计入
    `unresolved_refs`——不静默产出一条永不成立的规则。
    """
    if not members.has("minecraft:block", tag_id):
        return None
    table = members.members("minecraft:block", tag_id)
    if not table:
        return None

    tag_head = tag_node("minecraft:block", tag_id)
    rules = [
        Rule(
            id=f"worldgen:{fact.prov.file}#{index}",
            head=tag_head,
            body=(DEFAULT_WORLD,),
            kind="seeds",
            family=FAMILY,
            meta={"source": "tag_placement", "tag": tag_id},
            prov=fact.prov,
        )
    ]
    for member in sorted(table):
        rules.append(
            Rule(
                id=f"worldgen:{fact.prov.file}#{index}:{member}",
                head=node("block", member),
                body=(tag_head,),
                kind="implies",
                family=FAMILY,
                meta={"source": "tag_placement", "tag": tag_id},
                prov=fact.prov,
            )
        )
    return rules
