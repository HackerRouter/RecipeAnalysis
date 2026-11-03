import json

rows = [json.loads(l) for l in open("output/26.3/facts/loot_table.jsonl", encoding="utf-8")]
print("26.3 剪毛相关表：")
for r in rows:
    if "/shearing/" not in r["prov"]["file"]:
        continue
    items = [e["name"] for pool in r["payload"]["pools"] for e in pool["entries"] if e.get("name")]
    print(f"  {r['payload']['table']:<34} {items}")

print()
print("26.3 羊的死亡掉落表（entities/sheep*）：")
for r in rows:
    if "/entities/sheep" in r["prov"]["file"]:
        items = [e["name"] for pool in r["payload"]["pools"] for e in pool["entries"] if e.get("name")]
        print(f"  {r['payload']['table']:<34} {items}")
