"""统计 gaps 里剩余不可达的构成，按归因与缺项排序。"""

import collections
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

label = sys.argv[1] if len(sys.argv) > 1 else "26.3"
rows = [json.loads(l) for l in pathlib.Path(f"output/{label}/gaps.jsonl").open(encoding="utf-8")]

by_reason = collections.Counter(r["reason"] for r in rows)
print("归因:", dict(by_reason))

missing = collections.Counter()
for r in rows:
    for m in r.get("missing") or []:
        missing[m.split(":")[0]] += 1
print("缺项排序:", dict(missing.most_common()))

print("\n-- no_rule 样例 --")
for r in [x for x in rows if x["reason"] == "no_rule"][:10]:
    print(" ", r["node"])

print("\n-- blocked 前 12 --")
for r in [x for x in rows if x["reason"] == "blocked"][:12]:
    print(" ", r["node"], "<-", r.get("missing"))

print("\n-- cycle 环大小分布 --")
sizes = collections.Counter(len(r.get("cycle") or []) for r in rows if r["reason"] == "cycle_no_entry")
print(dict(sorted(sizes.items())))

print("\n-- cycle 样例 --")
for r in [x for x in rows if x["reason"] == "cycle_no_entry"][:6]:
    print(" ", r["node"], "->", r.get("cycle"))
