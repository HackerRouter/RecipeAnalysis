"""把不可达物品溯源到方块，再判断方块有没有自然来源。

这是一次性诊断：报告每个不可达物品「缺的是配方、世界生成、还是变换」。
"""

import collections
import json
import pathlib
import sys

sys.path.insert(0, "src")
sys.stdout.reconfigure(encoding="utf-8")

from oa.facts.schema import Fact, Prov, Status  # noqa: E402
from oa.facts.store import FactStore  # noqa: E402
from oa.ir.compile import compile_ir  # noqa: E402
from oa.solve.fixpoint import solve  # noqa: E402


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


def block_origin(block: str) -> str:
    rules = rule_set.of_head(block)
    if not rules:
        return "方块无任何规则"
    families = {r.family for r in rules}
    if "worldgen" in families:
        return "worldgen"
    if "code/transform" in families:
        return "变换"
    return "只有 place"


def item_block(item: str) -> str | None:
    for rule in rule_set.of_head(item):
        for body in rule.body:
            if body.startswith("table:"):
                for down in rule_set.of_head(body):
                    for leaf in down.body:
                        if leaf.startswith("block:"):
                            return leaf
    return None


buckets: collections.Counter = collections.Counter()
examples: dict[str, list[str]] = collections.defaultdict(list)

for node, value in states.items():
    if not node.startswith("item:") or getattr(value, "name", None) == "TRUE":
        continue
    rules = rule_set.of_head(node)
    families = {r.id.split(":")[0] for r in rules}
    if "recipe" in families:
        buckets["有配方"] += 1
        continue
    block = item_block(node)
    if block is None:
        buckets["无方块链路"] += 1
    else:
        key = block_origin(block)
        buckets[key] += 1
    if len(examples[buckets.most_common(1)[0][0]]) < 8:
        examples[key if block else "无方块链路"].append(node.partition(":")[2])

for key, count in buckets.most_common():
    print(f"{count:5d}  {key}")
    print(f"       {examples[key][:8]}")
