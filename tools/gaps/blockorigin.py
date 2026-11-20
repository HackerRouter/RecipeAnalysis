"""对不可达物品，看它依赖的方块有没有 worldgen 来源。

用来区分两类缺口：
- 方块有 worldgen 规则但没有被播种 → 桥接/锚定问题
- 方块根本没有 worldgen 规则 → 采集缺口（或该方块本就不自然生成）
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

no_worldgen: list[str] = []
has_worldgen: list[str] = []
other: list[str] = []

for row in (json.loads(l) for l in pathlib.Path(f"output/{label}/report/reachability.jsonl").open(encoding="utf-8")):
    if row["status"] == "true" or not row["node"].startswith("item:"):
        continue
    rules = rule_set.of_head(row["node"])
    families = {r.id.split(":")[0] for r in rules}
    if "recipe" in families:
        continue  # 配方类的缺口另行处理
    blocks = [b for r in rules for b in r.body if b.startswith("block:")]
    if not blocks:
        other.append(row["node"])
        continue
    covered = [b for b in blocks if any(r.family == "worldgen" for r in rule_set.of_head(b))]
    (has_worldgen if covered else no_worldgen).append(row["node"])

print(f"方块无 worldgen 来源: {len(no_worldgen)}")
print(" ", [n.partition(":")[2] for n in no_worldgen[:30]])
print(f"\n方块有 worldgen 却没通: {len(has_worldgen)}")
print(" ", [n.partition(":")[2] for n in has_worldgen[:20]])
print(f"\n其它（非方块掉落）: {len(other)}")
print(" ", [n.partition(":")[2] for n in other[:20]])
