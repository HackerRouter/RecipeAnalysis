"""变换族：`block_A → block_B` 的原地转换。

`transmutes`：同一位置、同一方块，换了个状态。来源是
`block_transform` 事实（当前版本里是 `BlockTransformer` 的注册表与代码表）。

``` 
block:minecraft:stripped_oak_wood  ←transmutes←  block:minecraft:oak_wood
                                                   tool:minecraft:axe
```

## 为什么 head 是方块而不是物品

变换发生在世界里，前提是那个方块已经摆在那儿。物品侧的可达性走另一条链：
`item:X ← table:blocks/X ← block:X`。把物品写进 head 会绕开「方块得先存在」
这一步，于是「从没见过的方块」也能凭空产出物品。

## 为什么工具是硬前置

斧子不成立时剥皮不成立，这不是概率事件。工具的成立由 `bridge/tool` 给
（`tool:axe ← tag:item/minecraft:axes`），不在这里枚举具体斧头。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...facts import Fact
from ..nodes import Rule, node, split_node

FAMILY = "code/transform"


@dataclass
class TransformCompileResult:
    rules: list[Rule] = field(default_factory=list)
    # 认不出 `transformer_kind` 的事实（不静默跳过）
    unknown_transformer_kind: list[str] = field(default_factory=list)
    # `from` 或 `to` 不是方块节点
    malformed: list[str] = field(default_factory=list)
    # 变换器没有对应的工具节点（如代码表里的私有映射）
    unmapped_transformer: dict[str, int] = field(default_factory=dict)


def _soft_nodes(raw: object, result: TransformCompileResult, prov_file: str) -> list[str]:
    """把 `soft` 里的位置约束还原成节点。

    事实里的形状是 `above=tag:minecraft:air`：等号左边是位置谓词，右边才是
    世界状态节点。等号左边不进 IR（IR 不表达空间关系），右边当软约束保留。
    还原不出来的条目留痕，不静默跳过。
    """
    out: list[str] = []
    for value in raw or []:
        if not isinstance(value, str):
            result.malformed.append(prov_file)
            continue
        _, sep, tail = value.partition("=")
        candidate = tail if sep else value
        try:
            split_node(candidate)
        except ValueError:
            result.malformed.append(f"{prov_file}#soft:{value}")
            continue
        out.append(candidate)
    return out


def compile_transforms(
    facts: list[Fact],
    tool_classes: dict[str, str | None],
    inverse_map: dict[str, dict] | None = None,
) -> TransformCompileResult:
    """`block_transform` 事实 → `transmutes` 规则。"""
    result = TransformCompileResult()
    inverse_map = inverse_map or {}
    # 一个文件可产多条变换（同一个 transformer 下按方块枚举），
    # 只用文件名当 id 会撞，加序号
    sequence = 0

    for fact in facts:
        payload = fact.payload
        target = payload.get("to")
        sources = payload.get("from") or []
        if not isinstance(target, str) or not isinstance(sources, list) or not sources:
            result.malformed.append(fact.prov.file)
            continue

        try:
            target_sort, target_id = split_node(target)
        except ValueError:
            result.malformed.append(fact.prov.file)
            continue
        if target_sort != "block":
            result.malformed.append(fact.prov.file)
            continue

        body: list[str] = []
        ok = True
        for source in sources:
            if not isinstance(source, str):
                ok = False
                break
            try:
                source_sort, _ = split_node(source)
            except ValueError:
                ok = False
                break
            if source_sort != "block":
                ok = False
                break
            body.append(source)
        if not ok:
            result.malformed.append(fact.prov.file)
            continue

        transformer = payload.get("transformer")
        kind = payload.get("transformer_kind")
        if not isinstance(transformer, str):
            result.unmapped_transformer["<无变换器>"] = (
                result.unmapped_transformer.get("<无变换器>", 0) + 1
            )
            continue

        if kind == "registry":
            # 工具类映射没有登记时，这条变换进不了 IR：不猜「任意物品都行」
            if transformer not in tool_classes:
                result.unmapped_transformer[transformer] = (
                    result.unmapped_transformer.get(transformer, 0) + 1
                )
                continue
            body.append(node("tool", transformer))
        elif kind == "code_table":
            # 代码里的私有映射（如铜箱合并），没有对应的物品形态，留痕不猜
            result.unknown_transformer_kind.append(
                f"{transformer}（{fact.prov.file}）"
            )
            continue
        else:
            result.unknown_transformer_kind.append(
                f"{transformer}:{kind}（{fact.prov.file}）"
            )
            continue

        soft = tuple(_soft_nodes(payload.get("soft"), result, fact.prov.file))

        sequence += 1
        result.rules.append(
            Rule(
                id=f"transmute:{fact.prov.file}#{sequence}",
                head=node("block", target_id),
                body=tuple(body),
                soft=soft,
                kind="transmutes",
                family=FAMILY,
                meta={
                    "transformer": transformer,
                    "sound": payload.get("sound"),
                    "damage_per_use": payload.get("damage_per_use"),
                },
                prov=fact.prov,
            )
        )

        # 反方向：同一组方块关系换个前提。依据在 `transform_inverse.json`，
        # 不在这里判断哪个 sound 可逆
        inverse = inverse_map.get(str(payload.get("sound") or ""))
        if isinstance(inverse, dict):
            requires = tuple(
                item for item in (inverse.get("requires") or []) if isinstance(item, str)
            )
            for source in sources:
                _, source_id = split_node(source)
                sequence += 1
                result.rules.append(
                    Rule(
                        id=f"transmute:{fact.prov.file}#{sequence}:inverse",
                        head=node("block", source_id),
                        body=(node("block", target_id), *requires),
                        soft=soft,
                        kind="transmutes",
                        family=FAMILY,
                        meta={
                            "inverse": True,
                            "transformer": None,
                            "sound": payload.get("sound"),
                            "basis": inverse.get("basis", ""),
                        },
                        prov=fact.prov,
                    )
                )

    return result
