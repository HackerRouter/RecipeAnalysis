"""枚举 block_transformer 数据文件里出现的全部 type 与字段，落 UTF-8。

用途：为适配器写「未知字段报错」的完整清单。不允许凭印象补字段。
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("inputs/26.3/src/main/resources/data/minecraft/block_transformer")
OUT = Path("output/bt-shapes.txt")

entry_keys: Counter = Counter()
providers: Counter = Counter()
predicate_types: Counter = Counter()
predicate_keys: dict[str, Counter] = defaultdict(Counter)
then_types: Counter = Counter()
then_keys: dict[str, Counter] = defaultdict(Counter)
rule_keys: Counter = Counter()
blocks_forms: Counter = Counter()
top_type: Counter = Counter()
transform_types: Counter = Counter()
tag_predicates: Counter = Counter()
offsets: Counter = Counter()


def walk_predicate(pred, depth: int) -> None:
    pt = pred.get("type", "<no-type>")
    predicate_types[pt] += 1
    predicate_keys[pt].update(pred.keys())
    if "blocks" in pred:
        blocks_forms[type(pred["blocks"]).__name__] += 1
    if "tag" in pred:
        tag_predicates[pred["tag"]] += 1
    if "offset" in pred:
        offsets[json.dumps(pred["offset"])] += 1
    for sub in pred.get("predicates", []):
        walk_predicate(sub, depth + 1)


for path in sorted(ROOT.glob("*.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    top_type[type(doc).__name__] += 1
    for entry in doc:
        entry_keys.update(entry.keys())
        if "transform_type" in entry:
            transform_types[entry["transform_type"]] += 1
        provider = entry["block_state_provider"]
        ptype = provider.get("type", "<no-type>")
        providers[ptype] += 1
        for rule in provider.get("rules", []):
            rule_keys.update(rule.keys())
            walk_predicate(rule["if_true"], 0)
            then = rule["then"]
            tt = then.get("type", "<no-type>")
            then_types[tt] += 1
            then_keys[tt].update(then.keys())

lines = [f"top-level JSON type: {dict(top_type)}", ""]
lines.append(f"entry keys        : {sorted(entry_keys)}")
for k, v in entry_keys.most_common():
    lines.append(f"    {k}: {v}")
lines.append("")
lines.append(f"provider types    : {dict(providers)}")
lines.append("")
lines.append(f"rule keys         : {sorted(rule_keys)}")
lines.append("")
lines.append(f"predicate types   : {dict(predicate_types)}")
for t, c in predicate_keys.items():
    lines.append(f"    {t}: {sorted(c)}  {dict(c)}")
lines.append("")
lines.append(f"'blocks' forms    : {dict(blocks_forms)}")
lines.append(f"transform_type    : {dict(transform_types)}")
lines.append(f"tags in predicate : {dict(tag_predicates)}")
lines.append(f"offsets           : {dict(offsets)}")
lines.append("")
lines.append(f"then types        : {dict(then_types)}")
for t, c in then_keys.items():
    lines.append(f"    {t}: {sorted(c)}  {dict(c)}")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
print("\n".join(lines))
