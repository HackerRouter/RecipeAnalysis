"""列出「只有 places 规则、没有 worldgen 来源」的方块。

这类方块在 IR 里只能靠玩家放置成立，于是它的物品与方块互为前提（环）。
它们要么是自然生成的（采集缺口），要么本来只能合成（应当有配方）。
"""

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

orphans: list[str] = []
transmuted: list[str] = []

for head in sorted({r.head for r in rule_set.rules if r.head.startswith("block:")}):
    rules = rule_set.of_head(head)
    families = {r.family for r in rules}
    if "worldgen" in families:
        continue
    if "code/transform" in families:
        transmuted.append(head)
        continue
    ids = {r.id.split(":")[0] for r in rules}
    if ids == {"code"}:
        orphans.append(head)

print(f"只有 places（无 worldgen、无变换）: {len(orphans)}")
for head in orphans:
    print(" ", head.partition(":")[2])
print(f"\n只有变换（无 worldgen）: {len(transmuted)}")
