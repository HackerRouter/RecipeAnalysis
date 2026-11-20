"""把不可达物品按名字形态聚类，找出集中的缺口块。"""

import collections
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

label = sys.argv[1] if len(sys.argv) > 1 else "26.3"
nodes = [
    json.loads(l)["node"]
    for l in pathlib.Path(f"output/{label}/report/reachability.jsonl").open(encoding="utf-8")
]
gaps = {
    json.loads(l)["node"]
    for l in pathlib.Path(f"output/{label}/report/gaps.jsonl").open(encoding="utf-8")
}
for line in pathlib.Path(f"output/{label}/report/reachability.jsonl").open(encoding="utf-8"):
    row = json.loads(line)
    if row.get("reason") == "no_rule":
        gaps.add(row["node"])

buckets: collections.Counter = collections.Counter()
members: dict[str, list[str]] = collections.defaultdict(list)

for node in sorted(gaps):
    name = node.partition(":")[2].partition(":")[2]
    # 去掉颜色前缀与形状后缀，聚到材质
    key = re.sub(r"^(white|orange|magenta|light_blue|yellow|lime|pink|gray|light_gray|cyan|"
                 r"purple|blue|brown|green|red|black)_", "COLOR_", name)
    key = re.sub(r"_(slab|stairs|wall|fence|fence_gate|door|trapdoor|button|pressure_plate|sign)$", "_*", key)
    buckets[key] += 1
    members[key].append(name)

print(f"不可达物品 {len(gaps)} 个，聚成 {len(buckets)} 类：")
for key, count in buckets.most_common(40):
    print(f"  {count:4d}  {key}")
