"""idiom：袭击波次表。

```java
private static enum RaiderType {
    VINDICATOR(EntityTypes.VINDICATOR, new int[]{0, 0, 2, 0, 1, 4, 2, 5}),
    EVOKER(EntityTypes.EVOKER,         new int[]{0, 0, 0, 0, 0, 1, 1, 2}),
    PILLAGER(EntityTypes.PILLAGER,     new int[]{0, 4, 3, 3, 4, 4, 4, 2}),
    WITCH(EntityTypes.WITCH,           new int[]{0, 0, 0, 0, 3, 0, 0, 1}),
    RAVAGER(EntityTypes.RAVAGER,       new int[]{0, 0, 0, 1, 0, 1, 0, 2});
}
```

枚举名 → 实体，数组是**每波刷几只**，下标即波次（`groupNumber = groupsSpawned + 1`，
所以第 0 位永不被读）。两版形态一致，只是 `EntityTypes` 与 `EntityType` 两种前缀。

## 为什么保留 0

0 表示「这一波不刷它」。只记非零项会让「第 2 波没有卫道士」这条信息消失，
下游按波次求总量时就无从区分「0 只」与「这一波没这个实体」。

## 波数与难度

实际波数由难度决定（简单 3、普通 5、困难 7），另有奖励波：
`shouldSpawnBonusGroup()` 为真时数量取 `spawnsPerWaveBeforeBonus[numGroups]`。
这层映射在 `Raid#getNumGroups` 里，是难度参数而非获取关系，
写进 `assume:raid` 的依据与 ADR 0013，不在此产事实。

## 形状

```
entity:minecraft:vindicator  ←spawns←  assume:raid   (meta: wave=3, count=2)
```

一条规则一个 (实体, 波次)。`meta.count` 是**基础数量**，不含
`getPotentialBonusSpawns` 按难度追加的随机增量——那部分是运行期随机，不是表。
"""

from __future__ import annotations

import re

from ..index import JavaIndex
from .base import Idiom, IdiomResult, Link

ID = "raid_waves"

# `VINDICATOR(EntityTypes.VINDICATOR, new int[]{0, 0, 2, ...})`
RAIDER_TYPE = re.compile(
    r"([A-Z][A-Z0-9_]*)\s*\(\s*(?:EntityTypes|EntityType)\.([A-Z][A-Z0-9_]*)\s*,\s*"
    r"new\s+int\s*\[\s*\]\s*\{([^}]*)\}"
)

WAVE_TABLE = "Raid"

# 袭击只发生在主世界的村庄，与维度无关；用假设节点表达「袭击可发生」。
RAID_ASSUMPTION = "assume:raid"


class RaidWaves(Idiom):
    id = ID
    needs = ("Raid.RaiderType 数组",)
    # 两版都是 5 个实体 × 8 波；低于 20 条说明匹配退化。
    min_hits = 20

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        java = index.load(WAVE_TABLE)
        if java is None:
            result.note("未找到 Raid.java，袭击波次表将缺失")
            return result

        matches = list(RAIDER_TYPE.finditer(java.text))
        if not matches:
            result.note(
                f"{java.path}: 没找到 RaiderType 枚举；"
                "若该版本改了实现，需新增 idiom 或登记人工例外"
            )
            return result

        for match in matches:
            entity = match.group(2).lower()
            counts = [
                int(token) for token in re.findall(r"\d+", match.group(3))
            ]
            if not counts:
                result.note(f"{java.path}: {entity} 的波次数组为空，跳过")
                continue
            # 第 0 位不被读取（`groupNumber` 从 1 起），但保留它才能让下标等于波次。
            for wave, count in enumerate(counts):
                if wave == 0:
                    continue
                result.add(
                    Link(
                        head=f"entity:minecraft:{entity}",
                        kind="spawns",
                        via=(RAID_ASSUMPTION,),
                        meta={"wave": wave, "count": count},
                    ),
                    ID,
                    java.path,
                    f"Raid$RaiderType.{match.group(1)}#{wave}",
                )

        result.note(
            f"{java.path}: 波数由难度决定（简单 3 / 普通 5 / 困难 7），"
            "奖励波的数量取 spawnsPerWaveBeforeBonus[numGroups]；"
            "本 idiom 只给出基础数量，随机增量在 getPotentialBonusSpawns"
        )
        return result


def exported() -> list[Idiom]:
    return [RaidWaves()]
