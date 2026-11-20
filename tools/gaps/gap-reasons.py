import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

label = sys.argv[1] if len(sys.argv) > 1 else "26.3"
rows = [json.loads(l) for l in pathlib.Path(f"output/{label}/report/gaps.jsonl").open(encoding="utf-8")]
for r in sorted(rows, key=lambda x: (x["reason"], x["node"])):
    print(f"{r['reason']:16} {r['node'].split(':', 1)[1]:48} {r.get('missing')}")
