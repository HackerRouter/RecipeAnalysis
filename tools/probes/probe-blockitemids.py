"""看 BlockItemIds 里若干常量的真实值。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

text = Path("inputs/26.3/src/main/java/net/minecraft/references/BlockItemIds.java").read_text(
    encoding="utf-8"
)
pattern = re.compile(r'\b([A-Z][A-Z0-9_]*)\s*=\s*\w+\.create\("([a-z0-9_/]+)"\)')
mapping = dict(pattern.findall(text))
for name in ("REDSTONE_DUST", "REDSTONE_WIRE", "POWDER_SNOW", "CARROT_CROP", "TRIPWIRE", "COCOA", "PUMPKIN_STEM", "STONE"):
    print(f"  {name:16s} -> {mapping.get(name, 'MISS')}")
print(f"总常量 {len(mapping)}")
