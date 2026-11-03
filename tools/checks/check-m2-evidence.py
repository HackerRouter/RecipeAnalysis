"""核对 M2 验收条目在事实层是否已具备证据（不含 IR）。

M2 的判据是可达性结论，需要 IR。但可以先验「事实层有没有那条边」——
如果连证据都没有，说明阶段一还有洞，不只是缺 IR。
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path("output/m2-evidence.txt")
lines: list[str] = []

PROBES = {
    "iron_ingot": ["iron_ingot"],
    "dragon_head": ["dragon_head"],
    "elytra": ["elytra"],
    "white_wool": ["white_wool"],
    "tadpole_bucket": ["tadpole_bucket"],
}


def load(label: str, kind: str) -> list[dict]:
    path = Path("output") / label / "facts" / f"{kind}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8")]


for label in ("26.3", "1.18.2"):
    lines.append(f"########## {label} ##########")
    loot = load(label, "loot_table")
    recipe = load(label, "recipe")
    code = load(label, "code_link")
    trade = load(label, "trade")
    template = load(label, "template")

    for name, needles in PROBES.items():
        lines.append(f"\n--- {name}")
        hits: dict[str, int] = defaultdict(int)

        for fact in loot:
            blob = json.dumps(fact["payload"], ensure_ascii=False)
            if any(n in blob for n in needles):
                hits["loot_table"] += 1
        for fact in recipe:
            blob = json.dumps(fact["payload"], ensure_ascii=False)
            if any(n in blob for n in needles):
                hits["recipe"] += 1
        for fact in code:
            blob = json.dumps(fact["payload"], ensure_ascii=False)
            if any(n in blob for n in needles):
                idiom = fact["payload"]["idiom"]
                hits[f"code_link/{idiom}"] += 1
        for fact in trade:
            blob = json.dumps(fact["payload"], ensure_ascii=False)
            if any(n in blob for n in needles):
                hits["trade"] += 1
        for fact in template:
            blob = json.dumps(fact["payload"], ensure_ascii=False)
            if any(n in blob for n in needles):
                hits["template"] += 1

        if hits:
            for key, count in sorted(hits.items()):
                lines.append(f"    {key:28s} {count}")
        else:
            lines.append("    事实层没有任何证据")
    lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
