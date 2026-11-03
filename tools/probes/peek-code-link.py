"""统计 code_link 事实的 idiom / kind 分布（两版）。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "code_link.jsonl"
    if not path.exists():
        print(f"=== {label}: 无 code_link")
        continue
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    print(f"=== {label}  {len(rows)} rows")
    for (idiom, kind), count in sorted(Counter((r["payload"]["idiom"], r["payload"]["link"]["kind"]) for r in rows).items()):
        print(f"  {count:4d}  {idiom:26s} {kind}")
    print()
