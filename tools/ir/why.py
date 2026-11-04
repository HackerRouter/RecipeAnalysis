"""诊断单个物品为什么不可达：打印它的判定链。

**已被 `ra why --label <版本> <物品>` 取代**，后者会枚举全部途径并展开到起点。
本脚本留着是因为它只读 `reachability.jsonl`、不重算规则，核对报告本身时更快：
如果 `ra why` 与它对不上，说明规则集与报告产自不同的输入。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

label = sys.argv[1] if len(sys.argv) > 1 else "26.3"
targets = sys.argv[2:] or [
    "item:minecraft:iron_ingot",
    "item:minecraft:cobblestone",
    "item:minecraft:oak_log",
    "item:minecraft:furnace",
    "block:minecraft:stone",
    "table:minecraft:blocks/stone",
]

base = Path("output") / label
rows = {
    json.loads(line)["node"]: json.loads(line)
    for line in (base / "reachability.jsonl").open(encoding="utf-8")
}

for target in targets:
    row = rows.get(target)
    if row is None:
        print(f"{target}: 不在 reachability（不是 item 节点）")
        continue
    print(f"{target}: {row['status']}")
    if row["status"] != "true":
        for key in ("reason", "rule", "blocked_by", "note", "cycle"):
            if key in row:
                print(f"   {key}: {row[key]}")
    else:
        proof = row.get("proof") or []
        for step in proof[:4]:
            print(f"   {step['node']} ← {step['rule']}")
            print(f"      body: {step['body']}")
    print()

# 归因分布
from collections import Counter

reasons = Counter(r.get("reason") for r in rows.values() if r["status"] != "true")
print("归因分布:", dict(reasons))

# 最常见的第一缺项
blocked_by: Counter = Counter()
for r in rows.values():
    if r.get("reason") == "blocked":
        for item in r.get("blocked_by") or []:
            blocked_by[item.split(":")[0]] += 1
print("blocked 缺项按排序:", dict(blocked_by))
