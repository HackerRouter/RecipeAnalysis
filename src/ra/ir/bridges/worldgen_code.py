"""代码驱动的世界生成：`block:X ←seeds← world`，依据是特征实现类而不是特征 JSON。

绝大多数世界生成方块的方块名写在 `worldgen/feature/*.json` 里，由
`compile_worldgen` 的 `references` 直接得到。有一类特征不写：JSON 只有参数
（电量、扩散次数、概率），方块名落在实现类里。

`sculk_patch` 是最典型的：

```json
// worldgen/feature/sculk_patch_deep_dark.json —— 没有任何方块字段
{"type": "minecraft:sculk_patch", "amount_per_charge": 32, "charge_count": 10, ...}
```

```java
// SculkPatchFeature#place 只创建扩散器，方块名在别处
SculkSpreader spreader = SculkSpreader.createWorldGenSpreader();
...
// SculkVeinBlock#attemptPlaceSculk 才写出方块
BlockState defaultSculk = Blocks.SCULK.defaultBlockState();
```

于是该特征铺出来的幽匿在事实里没有来源，`block:minecraft:sculk` 只剩
「方块 ← 物品 ← 方块掉落表」这一圈循环。

## 为什么不做成 idiom

idiom 的判据必须是「一个固定的代码形状」。这里没有：特征类只引用扩散器，
方块名在另一个包的方块类里，中间隔着 `SculkSpreader` 与 `SculkBehaviour`
两层间接调用。按「特征类里的 `Blocks.X`」提取会取到 `Blocks.WATER`
（那是地形判据），按「扩散器可达的方块类」提取则要为这一个特征写一套
专用的调用链分析，等于把一条知识伪装成提取器。

## 落点与门控

表在 `knowledge/maps/mechanism/worldgen_code_blocks.json`，键是特征类型，
值是它铺出的方块。编译时逐条门控：

1. 该版本必须存在这个特征类型的 `worldgen` 事实——1.18.2 没有 deep dark，
   自然不产；
2. 方块必须在 block 注册表里，写错记 `unknown_block`，不静默丢弃。

两条门控合起来保证：表可以同时写多个版本的机制，不会在旧版本造出节点。
"""

from __future__ import annotations

from collections import Counter

from ...facts import Fact
from ..nodes import Rule, node

FAMILY = "bridge/worldgen_code"
DEFAULT_WORLD = "world:minecraft:overworld"


def _local(ident: object) -> str | None:
    """`minecraft:sculk_patch` → `sculk_patch`。事实里的类型引用是短名。"""
    if not isinstance(value := ident, str) or not value:
        return None
    return value.split(":", 1)[-1]


def worldgen_code_rules(
    facts: list[Fact],
    mapping: dict[str, dict],
    block_ids: set[str],
) -> tuple[list[Rule], dict[str, int]]:
    """特征实现类里的方块 → `block:X ←seeds← world`。

    `facts` 是该版本的 `worldgen` 事实。门控是**该版本有特征引用这个类型**：
    特征 JSON 的顶层 `type` 往往只是容器（`sequence`），真正用到
    `sculk_patch` 的是 `features` 数组里的元素，所以按 `references` 的 id 匹配。

    没有这个引用就没有规则，因此表里可以同时写多个版本的机制。
    """
    stats: Counter = Counter()
    rules: list[Rule] = []

    # 键统一成短名，供与 references 的 id 比较
    wanted = {key.split(":", 1)[-1]: key for key in mapping}

    # 先按类型归并：同一个特征类型可能有多个 feature 文件
    # （`sculk_patch_deep_dark` 与 `sculk_patch_ancient_city` 同类型）。
    by_type: dict[str, list[Fact]] = {}
    for fact in facts:
        if fact.payload.get("worldgen_kind") != "feature":
            continue
        seen: set[str] = set()
        for ref in fact.payload.get("references") or []:
            if not isinstance(ref, dict):
                continue
            local = _local(ref.get("id"))
            if local is None or local not in wanted or local in seen:
                continue
            seen.add(local)
            by_type.setdefault(wanted[local], []).append(fact)

    for key, matched in sorted(by_type.items()):
        spec = mapping[key]
        if not isinstance(spec, dict):
            stats[f"{key}:spec_invalid"] += 1
            continue
        blocks = spec.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            stats[f"{key}:no_blocks"] += 1
            continue

        feature_ids = sorted(
            {
                str(fact.payload.get("id"))
                for fact in matched
                if isinstance(fact.payload.get("id"), str)
            }
        )
        for raw in blocks:
            if not isinstance(raw, str) or not raw:
                stats[f"{key}:bad_block"] += 1
                continue
            ident = raw if ":" in raw else f"minecraft:{raw}"
            if ident not in block_ids:
                # 写错或多写了该版本没有的方块：留痕，不产规则
                stats[f"{key}:unknown_block"] += 1
                continue
            rules.append(
                Rule(
                    id=f"{FAMILY}:{key}:{ident}",
                    head=node("block", ident),
                    body=(DEFAULT_WORLD,),
                    kind="seeds",
                    family=FAMILY,
                    meta={
                        "feature_type": key,
                        "features": feature_ids,
                        "basis": spec.get("basis", ""),
                        "evidence": spec.get("evidence", ""),
                        "source": "代码侧",
                    },
                    prov=matched[0].prov,
                )
            )
            stats["emitted"] += 1

    return rules, {key: int(value) for key, value in stats.items()}
