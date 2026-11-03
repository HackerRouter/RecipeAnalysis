"""最终对照：我的 code_link 与原型 extractor 的规模。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

print("=== 我的 code_link")
for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "code_link.jsonl"
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    by = Counter((r["payload"]["idiom"], r["payload"]["link"]["kind"]) for r in rows)
    print(f"{label}: {len(rows)} 条")
    for (idiom, kind), count in sorted(by.items()):
        print(f"  {count:4d}  {idiom:24s} {kind}")
    print()

print("=== 我的 block_transform")
for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "block_transform.jsonl"
    if not path.exists():
        print(f"{label}: 无")
        continue
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    by = Counter(r["payload"]["transformer_kind"] for r in rows)
    print(f"{label}: {len(rows)} 条  {dict(by)}")
print()

print("=== 原型反编译源码侧（对照用）")
for label in ("26.3", "1.18.2"):
    base = Path("ref/ObtainableAnalysis/facts") / label
    total = 0
    parts = []
    for path in sorted(base.glob("*.jsonl")):
        count = sum(1 for _ in path.open(encoding="utf-8"))
        if count:
            parts.append(f"{path.stem}={count}")
            total += count
    print(f"{label}: {total} 条")
    print("  " + "  ".join(parts))
