"""取证：两版 Blocks.java 里的「借用他人战利品表」写法。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CASES = (
    ("1.18.2", Path("inputs/1.18.2/src/main/java"), r"dropsLike\("),
    ("26.3", Path("inputs/26.3/src/main/java"), r"wallVariant\(|dropsLike\("),
)

for label, root, pattern in CASES:
    path = root / "net/minecraft/world/level/block/Blocks.java"
    if not path.is_file():
        print(f"=== {label}: 缺 {path}")
        continue
    text = path.read_text(encoding="utf-8")
    regex = re.compile(pattern)
    lines = [(i + 1, line.strip()) for i, line in enumerate(text.splitlines()) if regex.search(line)]
    print(f"=== {label}  {path.stat().st_size} bytes  {len(lines)} 命中行")
    for number, line in lines[:10]:
        print(f"  L{number}: {line[:190]}")
    print()
