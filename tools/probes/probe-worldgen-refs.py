"""统计世界生成引用里各种方块写法的出现次数，以及结构刷怪配置，供文档复算。

用法：`python tools/probes/probe-worldgen-refs.py 26.3`
"""

import collections
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

label = sys.argv[1] if len(sys.argv) > 1 else "26.3"
slots: collections.Counter = collections.Counter()
tags: list[str] = []
per_kind: collections.Counter = collections.Counter()

for line in pathlib.Path(f"output/{label}/facts/worldgen.jsonl").open(encoding="utf-8"):
    row = json.loads(line)
    p = row["payload"]
    for ref in p.get("references") or []:
        slots[ref.get("slot")] += 1
        if ref.get("slot") == "tag":
            tags.append(f"{ref['id']} @ {p.get('id')}")
        if ref.get("slot") == "block":
            per_kind[p.get("worldgen_kind")] += 1

print("slot 分布:", dict(slots.most_common()))
print("方块引用总数:", slots.get("block", 0))
print("标签放置引用:", len(tags))
for t in tags:
    print("   ", t)
print("按 worldgen_kind 的方块引用:", dict(per_kind.most_common(8)))

# 结构刷怪：`spawn_overrides` 进的是 `spawns` 字段，不混在 references 里
spawns: collections.Counter = collections.Counter()
files_with_spawns = 0
for line in pathlib.Path(f"output/{label}/facts/worldgen.jsonl").open(encoding="utf-8"):
    p = json.loads(line)["payload"]
    entries = p.get("spawns") or []
    if entries:
        files_with_spawns += 1
    for entry in entries:
        spawns[entry.get("entity")] += 1

print(f"\n结构刷怪：{files_with_spawns} 个结构、{sum(spawns.values())} 条")
for entity, count in spawns.most_common():
    print(f"  {count}  {entity}")
