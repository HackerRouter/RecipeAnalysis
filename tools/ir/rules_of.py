"""列出一个节点在 IR 里的全部规则，以及每条规则的 body 判定状态。

从 `output/<label>/facts/` 读回事实重建 IR，不依赖 inputs（只读产物即可复盘）。
与 `oa why` 的分工：本脚本列**规则**（含不成立的），`oa why` 追**路径**（只列成立的）。
"""

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
targets = sys.argv[2:]

store = load_store(label)
rule_set, report = compile_ir(store, pathlib.Path("."))
state = solve(rule_set, report.seeds)
states = state.states


def is_true(value) -> bool:
    return getattr(value, "name", None) == "TRUE" or value is True


for target in targets:
    rules = rule_set.of_head(target)
    print(f"\n=== {target}  状态 {states.get(target)}  规则 {len(rules)} 条 ===")
    for rule in rules:
        marks = [(b, states.get(b)) for b in rule.body]
        ok = all(is_true(v) for _, v in marks)
        print(f"  [{'OK' if ok else '  '}] {rule.id}")
        for body, value in marks:
            print(f"        {body}: {value}")
