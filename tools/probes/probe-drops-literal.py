"""统计：setItemSlot 里带 `new ItemStack(Items.X)` 字面量的调用。"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

LITERAL = re.compile(
    r"setItemSlot\s*\(\s*([A-Za-z0-9_.]+)\s*,\s*new\s+ItemStack\s*\(\s*Items\.([A-Z][A-Z0-9_]*)"
)

for label in ("26.3", "1.18.2"):
    root = Path("inputs") / label / "src/main/java/net/minecraft/world/entity"
    print(f"=== {label}")
    in_ai = 0
    outside = []
    for path in sorted(root.rglob("*.java")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in LITERAL.finditer(text):
            slot, item = match.group(1), match.group(2)
            if rel.startswith("ai/"):
                in_ai += 1
            else:
                line = text.count("\n", 0, match.start()) + 1
                outside.append((rel, line, slot, item))
    print(f"  ai/ 内 {in_ai} 处，ai/ 外 {len(outside)} 处")
    for rel, line, slot, item in outside:
        print(f"    {rel}:{line}  {slot} <- {item}")
    print()
