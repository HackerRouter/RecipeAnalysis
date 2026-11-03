"""`code_link` 事实 → 规则。

事实层已经与 IR 同构（`head` / `via` / `inputs` / `soft`），所以本模块几乎只做装配：

```
body = inputs + via
soft = soft
```

`via` 与 `inputs` 都进 `body`，因为两者都是硬前置——羊不存在要去生成，
剪刀不存在路径就断。区别在**播种**：`entity:*` / `block:*` / `structure:*` 由世界生成
播种为真，`item:*` 由配方链推导。这个区别由 `nodes.SEEDED_SORTS` 表达，
不需要在这里区分。

## 一处需要纠正：`places` 的前置藏在 meta 里

`places` 的事实形状是：

```json
{"head": "block:minecraft:redstone_wire", "kind": "places",
 "meta": {"item": "item:minecraft:redstone"}}
```

`head` 是方块，前置物品在 `meta.item`。事实层这样放的理由是「被放置的物品由
`meta` 表达，不重复计入 inputs」——对事实层成立，但求解器需要一个前置节点。
所以这里把它提进 `body`，并在 `meta` 里保留原值。

**不改事实层**：改 `Link` 的 `inputs` 会让「inputs = 消耗品」这条语义变模糊，
而放置消耗的确实是那件物品，只是它同时是 head 的成因。事实与规则的差异在这一层吸收。
"""

from __future__ import annotations

from ...facts import Fact
from ..nodes import NodeError, Rule


def compile_code(facts: list[Fact]) -> list[Rule]:
    rules: list[Rule] = []

    for seq, fact in enumerate(facts):
        payload = fact.payload
        idiom = payload.get("idiom")
        link = payload.get("link")
        if not isinstance(link, dict) or not isinstance(idiom, str):
            continue

        head = link.get("head")
        kind = link.get("kind")
        if not isinstance(head, str) or not isinstance(kind, str):
            continue

        via = [v for v in (link.get("via") or []) if isinstance(v, str)]
        inputs = [v for v in (link.get("inputs") or []) if isinstance(v, str)]
        soft = [s for s in (link.get("soft") or []) if isinstance(s, str)]
        meta = payload.get("meta") or {}

        body = [*inputs, *via]

        if kind == "places":
            placement = meta.get("item")
            if isinstance(placement, str):
                body.append(placement)
            else:
                raise NodeError(
                    f"{fact.prov.file}: places 链接缺少 meta.item，无法确定前置物品"
                )

        # 同一 idiom 可能对同一 head 产出多条事实（如一个结构里两处放了同一物品），
        # 所以 id 带序号，不能用 `file + head`
        rules.append(
            Rule(
                id=f"code:{idiom}:{fact.prov.file}:{head}#{seq}",
                head=head,
                body=tuple(dict.fromkeys(body)),
                soft=tuple(dict.fromkeys(soft)),
                kind="places" if kind == "places" else kind,
                family=f"code/{idiom}",
                meta=meta,
                prov=fact.prov,
            )
        )

    return rules
