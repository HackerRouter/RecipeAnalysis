"""看两版 BuiltInLootTables 的真实写法与 ColorCollection 定义。"""
import re
from pathlib import Path

p = Path("inputs/26.3/src/main/java/net/minecraft/world/level/storage/loot/BuiltInLootTables.java")
lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
print("=== 26.3 SHEAR_DYED_SHEEP 上下文 ===")
for i, line in enumerate(lines):
    if "SHEAR_DYED_SHEEP" in line:
        for j in range(max(0, i - 1), min(i + 5, len(lines))):
            print(f"  {j + 1:>4}: {lines[j]}")
        break

print()
print("=== 1.18.2 BuiltInLootTables 前 26 行 ===")
p2 = Path("inputs/1.18.2/src/main/java/net/minecraft/world/level/storage/loot/BuiltInLootTables.java")
if p2.exists():
    for i, line in enumerate(p2.read_text(encoding="utf-8", errors="replace").splitlines()[:26], 1):
        print(f"  {i:>4}: {line}")
else:
    print("  MISS")

print()
print("=== ColorCollection.java ===")
for c in Path("inputs/26.3/src/main/java").rglob("ColorCollection.java"):
    text = c.read_text(encoding="utf-8", errors="replace")
    print(f"  {c}")
    for i, line in enumerate(text.splitlines()[:70], 1):
        if re.search(r"NAMES|EnumSet|DyeColor\.|class ColorCollection", line):
            print(f"    {i:>4}: {line.strip()[:130]}")
