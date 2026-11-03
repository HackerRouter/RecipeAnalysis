"""统计两版战利品表里出现的条件与函数类型。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path("output/loot-types.txt")
lines: list[str] = []


def walk_entries(entry: object, cond: Counter, func: Counter) -> None:
    """适配器已把 children 摊平到同层，`children` 只是计数，不是子条目列表。"""
    if not isinstance(entry, dict):
        return
    for item in entry.get("conditions") or []:
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            cond[item["type"]] += 1
        elif isinstance(item, str):
            cond[f"<ref:{item}>"] += 1
    for item in entry.get("functions") or []:
        if isinstance(item, dict) and isinstance(item.get("function"), str):
            func[item["function"]] += 1


for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "loot_table.jsonl"
    cond: Counter = Counter()
    func: Counter = Counter()
    kinds: Counter = Counter()
    for line in path.open(encoding="utf-8"):
        fact = json.loads(line)
        for pool in fact["payload"].get("pools") or []:
            for item in pool.get("conditions") or []:
                if isinstance(item, dict) and isinstance(item.get("type"), str):
                    cond[item["type"]] += 1
            for item in pool.get("functions") or []:
                if isinstance(item, dict) and isinstance(item.get("function"), str):
                    func[item["function"]] += 1
            for entry in pool.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                kinds[entry.get("kind")] += 1
                walk_entries(entry, cond, func)

    lines.append(f"=== {label}")
    lines.append(f"  条目类型: {dict(kinds)}")
    lines.append(f"  条件类型 {len(cond)}:")
    for name, count in cond.most_common():
        lines.append(f"    {count:5d}  {name}")
    lines.append(f"  函数类型 {len(func)}:")
    for name, count in func.most_common():
        lines.append(f"    {count:5d}  {name}")
    lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
