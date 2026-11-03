"""看原型各类边的 schema，落 UTF-8 文件（避免 PowerShell 重定向的 UTF-16 坑）。"""
import json
import os
from collections import Counter
from pathlib import Path

SAMPLES = 2
OUT = Path("output/proto-schema.txt")


def render(label: str, files: list[str], out: list[str]) -> None:
    base = os.path.join("ref", "ObtainableAnalysis", "facts", label)
    for name in files:
        path = os.path.join(base, name)
        if not os.path.exists(path):
            out.append(f"  {name}: MISS")
            continue
        rows = [json.loads(l) for l in open(path, encoding="utf-8")]
        if not rows:
            out.append(f"  {name}: 0 rows")
            continue
        out.append(f"  {name}  {len(rows)} rows")
        out.append(f"    keys   : {sorted(rows[0])}")
        out.append(f"    kind   : {dict(Counter(r.get('kind') for r in rows))}")
        out.append(f"    family : {dict(Counter(r.get('family') for r in rows))}")
        for row in rows[:SAMPLES]:
            short = {}
            for k, v in row.items():
                s = json.dumps(v, ensure_ascii=False)
                short[k] = s if len(s) <= 88 else s[:85] + "..."
            out.append(f"    sample : {short}")
        out.append("")


lines: list[str] = ["########## 26.3 source-side ##########"]
render("26.3", [
    "transforms_source.jsonl", "transforms_data.jsonl", "loot_alias.jsonl",
    "drops_source.jsonl", "mob_sources.jsonl", "place_source.jsonl",
    "code_placement.jsonl", "gadgets.jsonl", "interactions.jsonl",
], lines)

lines.append("########## 1.18.2 source-side ##########")
render("1.18.2", [
    "trades_source.jsonl", "recolor_source.jsonl", "entity_from_item.jsonl",
    "transforms_source.jsonl", "loot_alias.jsonl", "drops_source.jsonl",
], lines)

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
