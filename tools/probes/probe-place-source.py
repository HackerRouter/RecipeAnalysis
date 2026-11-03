"""取证：物品 ↔ 方块的注册期对应写法。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CASES = (
    ("26.3", Path("inputs/26.3/src/main/java/net/minecraft/world/item/Items.java")),
    ("1.18.2", Path("inputs/1.18.2/src/main/java/net/minecraft/world/item/Items.java")),
)

PATTERNS = (
    r"createBlockItemWithCustomItemName",
    r"registerSimpleBlockItem",
    r"registerBlock\w*",
    r"BlockItem\(",
)

for label, path in CASES:
    print(f"=== {label}  {path}")
    if not path.is_file():
        print("  缺文件")
        continue
    text = path.read_text(encoding="utf-8")
    print(f"  大小 {len(text)} 字符")
    for pattern in PATTERNS:
        regex = re.compile(pattern)
        hits = regex.findall(text)
        print(f"  {pattern:36s} {len(hits)}")
        for match in list(regex.finditer(text))[:2]:
            start = text.rfind("\n", 0, match.start()) + 1
            end = text.find("\n", match.end())
            print(f"      {text[start:end].strip()[:170]}")
    print()
