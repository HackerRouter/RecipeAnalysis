"""看两个新 idiom 的产出细节。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

for label in ("26.3", "1.18.2"):
    path = Path("output") / label / "facts" / "code_link.jsonl"
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    print(f"=== {label}")
    for row in rows:
        payload = row["payload"]
        if payload["idiom"] not in ("structure_gadgets", "mob_buckets"):
            continue
        link = payload["link"]
        print(f"  {payload['idiom']:18s} {link['kind']:7s} {link['head']}")
        print(f"      via={link['via']} inputs={link['inputs']} meta={payload['meta']}")
    print()
