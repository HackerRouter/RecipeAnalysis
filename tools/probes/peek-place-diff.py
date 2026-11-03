"""列出物品名 ≠ 方块名的 place 链接。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "code_link.jsonl"
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    place = [r for r in rows if r["payload"]["idiom"] == "place_source"]
    diff = sorted(
        (r["payload"]["meta"]["item"].split(":", 2)[2], r["payload"]["link"]["head"].split(":", 2)[2])
        for r in place
        if not r["payload"]["meta"]["same_name"]
    )
    print(f"=== {label}: {len(place)} 条 place，其中 {len(diff)} 条物品名 ≠ 方块名")
    for item, block in diff:
        print(f"  {item:26s} -> {block}")
    print()
