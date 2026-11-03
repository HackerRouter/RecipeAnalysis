"""战利品方言探测。

26.3 与 1.18.2 的两种方言靠**互斥信号**区分，不靠版本号：

| 方言 | 信号 |
|---|---|
| modern | `random_sequence` 键、条目级单数 `condition`、`type` 键、`modifier` |
| legacy | `conditions` 数组、条目级 `conditions` 键、`functions`、`bonus_rolls` |

证据按样本计数，取多数；两侧相等即判 UNKNOWN，不猜。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .common import load_json_safe, sample
from .profile import UNKNOWN, Profile

LOOT_DIALECT_MODERN = "modern"
LOOT_DIALECT_LEGACY = "legacy"

NEW_SHAPE_KEYS = frozenset({"random_sequence"})
OLD_SHAPE_KEYS = frozenset({"conditions", "functions", "bonus_rolls"})

__all__ = ["probe_loot_dialect", "walk_entry_keys"]

# 下潜深度上限。战利品表嵌套（池 → 条目 → 子表 → …）不会太深，
# 但恶意或异常的输入不该把递归撑爆。
MAX_DEPTH = 6


def walk_entry_keys(doc: object, depth: int = 0) -> set[str]:
    """收集条目级键名，用于方言判定。只下潜已知容器键。"""
    if depth > MAX_DEPTH:
        return set()
    keys: set[str] = set()
    if isinstance(doc, dict):
        keys |= set(doc)
        for key in ("pools", "entries", "children", "functions", "modifier", "conditions"):
            child = doc.get(key)
            if isinstance(child, list):
                for item in child:
                    keys |= walk_entry_keys(item, depth + 1)
            elif isinstance(child, dict):
                keys |= walk_entry_keys(child, depth + 1)
    elif isinstance(doc, list):
        for item in doc:
            keys |= walk_entry_keys(item, depth + 1)
    return keys


def probe_loot_dialect(data_root: Path, profile: Profile) -> None:
    """用两套信号跑同一批样本，取证据多的一套。"""
    claim = profile.dirs.get("loot_table")
    if claim is None:
        profile.loot_dialect = UNKNOWN
        profile.add_unresolved("战利品表目录未定位，方言不可判定")
        return

    ns, _, dir_name = claim.path.partition("/")
    paths = sorted((data_root / ns / dir_name).rglob("*.json"))
    evidence: Counter[str] = Counter()
    for path in sample(paths):
        doc = load_json_safe(path)
        if not isinstance(doc, dict):
            continue
        keys = set(doc)
        entry_keys = walk_entry_keys(doc)
        if keys & NEW_SHAPE_KEYS or ("condition" in entry_keys and "conditions" not in entry_keys):
            evidence[LOOT_DIALECT_MODERN] += 1
        if entry_keys & OLD_SHAPE_KEYS:
            evidence[LOOT_DIALECT_LEGACY] += 1
        if "modifier" in entry_keys and "functions" not in entry_keys:
            evidence[LOOT_DIALECT_MODERN] += 1

    profile.loot_dialect_evidence = dict(evidence)
    if not evidence:
        profile.loot_dialect = UNKNOWN
        profile.add_unresolved("战利品方言无证据（样本全部为空表）")
        return
    if len(evidence) == 1:
        profile.loot_dialect = next(iter(evidence))
        return
    modern = evidence.get(LOOT_DIALECT_MODERN, 0)
    legacy = evidence.get(LOOT_DIALECT_LEGACY, 0)
    if modern == legacy:
        profile.loot_dialect = UNKNOWN
        profile.add_unresolved(f"战利品方言歧义：modern {modern} / legacy {legacy}")
    else:
        profile.loot_dialect = LOOT_DIALECT_MODERN if modern > legacy else LOOT_DIALECT_LEGACY
        profile.notes.append(
            f"战利品方言混用：modern {modern} / legacy {legacy}，取多数；"
            f"少数样本按方言分派时会各自解析"
        )
