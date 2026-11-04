"""把不可达物品按「它的规则形状」分类，找出每一类的根因。

分类维度：
- 有没有配方规则（`recipe:` 前缀）
- 有没有变换规则
- 是否只有 loot 规则（自然物/变换产物的典型形状）
"""

import collections
import json
import pathlib
import sys

sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8")

from ra.facts.schema import Fact, Prov, Status  # noqa: E402
from ra.facts.store import FactStore  # noqa: E402
from ra.ir.compile import compile_ir  # noqa: E402
from ra.solve.fixpoint import solve  # noqa: E402


def load_store(label: str) -> FactStore:
    store = FactStore(label=label)
    for path in sorted(pathlib.Path(f"output/{label}/facts").glob("*.jsonl")):
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            store.add(
                Fact(
                    kind=row["kind"],
                    payload=row["payload"],
                    prov=Prov(**row["prov"]),
                    status=Status(row["status"]),
                    missing=tuple(row.get("missing") or ()),
                    error=row.get("error"),
                )
            )
    return store


label = sys.argv[1] if len(sys.argv) > 1 else "26.3"
store = load_store(label)
rule_set, report = compile_ir(store, pathlib.Path("."))
result = solve(rule_set, report.seeds)
states = result.states

gaps = [
    json.loads(l)
    for l in pathlib.Path(f"output/{label}/gaps.jsonl").open(encoding="utf-8")
]

buckets = collections.Counter()
samples: dict[str, list[str]] = collections.defaultdict(list)

for row in gaps:
    target = row["node"]
    if not target.startswith("item:"):
        continue
    rules = rule_set.of_head(target)
    families = {r.id.split(":")[0] for r in rules}
    if not rules:
        key = "无任何规则"
    elif "recipe" in families:
        # 有配方但不成：看是不是所有配方都缺同一类材料
        key = "有配方但仍不成"
    elif families == {"loot"}:
        # 只有战利品表：自然物或变换产物
        block_heads = [
            b for r in rules for b in r.body if b.startswith("block:")
        ]
        if block_heads:
            key = "只 loot（方块掉落）+ 无方块来源"
        else:
            key = "只 loot（非方块来源）"
    else:
        key = "其它:" + ",".join(sorted(families))
    buckets[key] += 1
    if len(samples[key]) < 6:
        samples[key].append(target.partition(":")[2])

print("不可达物品分类:")
for key, count in buckets.most_common():
    print(f"  {count:5d}  {key}")
    print(f"         {samples[key]}")

# 方块节点里有多少有 worldgen 规则
block_heads = {r.head for r in rule_set.rules if r.head.startswith("block:")}
print(f"\n方块节点总数 {len(block_heads)}；有 worldgen 规则 {len([r for r in rule_set.rules if r.family == 'worldgen' and r.head.startswith('block:')])} 条规则")
wg_heads = {r.head for r in rule_set.rules if r.family == "worldgen"}
print(f"worldgen 规则 head 数 {len(wg_heads)}，其中 block {len([h for h in wg_heads if h.startswith('block:')])}，entity {len([h for h in wg_heads if h.startswith('entity:')])}")
