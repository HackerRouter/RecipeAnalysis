"""量两版「结构生成代码里塞物品」的规模。

判据：`handleDataMarker` 内的 `markerId.startsWith("X")` 分支，
该分支里有 `new ItemStack(Items.Y)`。`elytra` 只是其中之一。
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BRANCH = re.compile(r'(\w+)\.startsWith\("([A-Za-z_]+)"\)')
ITEMSTACK = re.compile(r"new\s+ItemStack\(\s*Items\.([A-Z][A-Z0-9_]*)")

for label in ("26.3", "1.18.2"):
    root = Path("inputs") / label / "src/main/java/net/minecraft/world/level/levelgen/structure"
    print(f"=== {label}")
    total = 0
    for path in sorted(root.rglob("*.java")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "handleDataMarker" not in text:
            continue
        # 只看 handleDataMarker 方法体之后的部分
        start = text.find("handleDataMarker")
        body = text[start:]
        branches = BRANCH.findall(body)
        stacks = ITEMSTACK.findall(body)
        if not branches and not stacks:
            continue
        print(f"  {path.name}: marker 分支 {len(branches)}  ItemStack {len(stacks)}")
        for var, marker in branches:
            print(f"      marker: {marker}")
        for item in sorted(set(stacks)):
            print(f"      item:   {item}")
        total += len(branches)
    print(f"  合计 marker 分支 {total}")
    print()
