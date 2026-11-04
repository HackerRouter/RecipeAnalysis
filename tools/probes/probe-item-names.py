"""核实 3 条「物品名推断失败」的真实注册名。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from ra.paths import cache_root, repo_root

root = cache_root(repo_root())
reports = sorted(root.glob("*/reports/registries.json"))[0]
doc = json.loads(reports.read_text(encoding="utf-8"))
items = doc["minecraft:item"]["entries"]
print(f"物品总数 {len(items)}")

for probe in ("standstone", "sandstone", "grass", "dry"):
    hits = sorted(name for name in items if probe in name)
    print(f"\n含 {probe!r} 的注册名（{len(hits)}）：")
    for name in hits[:12]:
        print(f"  {name}")
