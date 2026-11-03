"""取证：实体自带装备（死后掉落）的写法。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PATTERNS = (
    r"setItemSlot\s*\(",
    r"EquipmentSlot\.[A-Z_]+",
)

for label in ("26.3", "1.18.2"):
    root = Path("inputs") / label / "src/main/java/net/minecraft/world/entity"
    print(f"=== {label}")
    if not root.is_dir():
        print("  缺目录")
        continue
    total = 0
    examples = []
    for path in sorted(root.rglob("*.java")):
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = len(re.findall(PATTERNS[0], text))
        if hits:
            total += hits
            if len(examples) < 6:
                for line in text.splitlines():
                    if "setItemSlot" in line:
                        examples.append((path.relative_to(root).as_posix(), line.strip()[:180]))
                        break
    print(f"  setItemSlot 调用 {total} 处")
    for rel, line in examples:
        print(f"    {rel}")
        print(f"      {line}")
    print()
