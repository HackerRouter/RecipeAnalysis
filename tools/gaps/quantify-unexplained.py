"""量化：数据包能解释多少物品，剩下多少只能靠代码或判为不可达。

不引入新概念，只用已产出的事实：
- registry 的 minecraft:item 全集
- recipe 的 result / results
- loot_table 的 item 条目
- trade 的 gives
"""
import json
from pathlib import Path


def load(label: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    base = Path("output") / label / "facts"
    for kind in ("registry", "recipe", "loot_table", "trade"):
        path = base / f"{kind}.jsonl"
        out[kind] = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return out


def local(ident: str) -> str:
    return ident.split(":", 1)[-1] if ":" in ident else ident


for label in ("26.3", "1.18.2"):
    facts = load(label)

    items: set[str] = set()
    for row in facts["registry"]:
        if row["payload"]["registry"] == "minecraft:item":
            items = {local(e) for e in row["payload"]["entries"]}
            break

    explained: dict[str, set[str]] = {"recipe": set(), "loot": set(), "trade": set()}

    for row in facts["recipe"]:
        p = row["payload"]
        for key in ("result", "results"):
            r = p.get(key)
            if isinstance(r, dict) and r.get("id"):
                explained["recipe"].add(local(r["id"]))
            elif isinstance(r, list):
                for x in r:
                    if isinstance(x, dict) and x.get("id"):
                        explained["recipe"].add(local(x["id"]))

    for row in facts["loot_table"]:
        for pool in row["payload"].get("pools") or []:
            for entry in pool.get("entries") or []:
                if entry.get("name"):
                    explained["loot"].add(local(entry["name"]))

    for row in facts["trade"]:
        p = row["payload"]
        if p.get("layer") == "offer" and p.get("gives", {}).get("id"):
            explained["trade"].add(local(p["gives"]["id"]))

    union = set().union(*explained.values())
    unexplained = items - union

    print(f"=== {label} ===")
    print(f"  注册表物品        {len(items)}")
    for kind, s in explained.items():
        print(f"  {kind:<9} 覆盖    {len(s):>5}")
    print(f"  并集覆盖          {len(union)}  ({len(union) / len(items):.1%})")
    print(f"  数据包解释不了     {len(unexplained)}  ({len(unexplained) / len(items):.1%})")
    print()
