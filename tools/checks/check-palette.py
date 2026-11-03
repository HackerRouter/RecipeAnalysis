"""对比两版模板 snbt 的 palette 是否有内容。

若 1.18.2 有内容而 26.3 全空，说明 26.3 这批文件被人为瘦身，
不是解析器 bug——那么 26.3 的「结构里有什么方块」就不可得，需要登记。
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PALETTE = re.compile(r"palette\s*:\s*\[(.*?)\n\s*\]", re.S)

for label, sub in (("26.3", "structure"), ("1.18.2", "structures")):
    root = Path("inputs") / label / "src/main/resources/data/minecraft" / sub
    if not root.is_dir():
        print(f"=== {label}: 目录不存在 {root}")
        continue
    files = sorted(root.rglob("*.snbt"))
    total = 0
    filled_files = 0
    sample = None
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        match = PALETTE.search(text)
        if match is None:
            continue
        items = re.findall(r'"([^"]*)"', match.group(1))
        total += len(items)
        filled = [i for i in items if i]
        if filled:
            filled_files += 1
            if sample is None:
                sample = (path.relative_to(root).as_posix(), len(filled), filled[:2])
    print(f"=== {label}  ({sub})")
    print(f"  snbt 文件 {len(files)}  palette 总项 {total}  含非空项的模板 {filled_files}")
    if sample:
        print(f"  样例 {sample[0]}: 非空 {sample[1]} 项，如前 {sample[2]}")
    print()
