"""检查 block_transform 事实的分布（两版）。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "block_transform.jsonl"
    if not path.exists():
        print(f"=== {label}: 无事实文件")
        continue
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    print(f"=== {label}  {len(rows)} rows")
    by = Counter(
        (r["payload"]["transformer_kind"], r["payload"]["transformer"].split("#")[-1], r["payload"]["mode"])
        for r in rows
    )
    for (kind, name, mode), count in sorted(by.items()):
        print(f"  {count:4d}  {kind:13s} {name:22s} {mode}")
    files = sorted({r["prov"]["file"] for r in rows})
    print(f"  files ({len(files)}):")
    for name in files:
        print(f"    {name}")
    print()
