"""看 jar 报告 blocks.json 的结构：是否含方块 ↔ 物品的对应。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from oa.paths import cache_root, repo_root

root = cache_root(repo_root())
candidates = sorted(root.glob("*/reports/blocks.json"))
if not candidates:
    candidates = sorted(root.glob("**/blocks.json"))
print(f"candidates: {[str(p) for p in candidates]}")

if not candidates:
    sys.exit()

path = candidates[0]
print(f"读 {path}  {path.stat().st_size} bytes")
doc = json.loads(path.read_text(encoding="utf-8"))
print(f"顶层类型 {type(doc).__name__}，条目 {len(doc)}")

sample_keys = list(doc)[:3]
for key in sample_keys:
    print(f"\n--- {key}")
    print(json.dumps(doc[key], ensure_ascii=False)[:600])

# 统计有哪些键
from collections import Counter

keys = Counter()
for value in doc.values():
    if isinstance(value, dict):
        keys.update(value.keys())
print(f"\nentry keys: {dict(keys)}")

# 有 item 键的条目数
with_item = sum(1 for v in doc.values() if isinstance(v, dict) and "item" in v)
print(f"带 item 的方块数: {with_item}")
