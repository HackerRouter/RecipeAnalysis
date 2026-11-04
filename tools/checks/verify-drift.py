"""验证台账漂移在真实输出目录上真会报。

做法：把上次台账里一条 `parsed` 改成 `failed`，再跑 ingest 比对。
"""
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "output" / "26.3" / "ledger.jsonl"

if not LEDGER.is_file():
    print("先跑一次 ingest 生成台账")
    sys.exit(1)

rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
target = next(r for r in rows if r["status"] == "parsed")
print(f"篡改 {target['file']}: parsed -> failed")
target["status"] = "failed"
LEDGER.write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
    encoding="utf-8",
    newline="\n",
)

result = subprocess.run(
    [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "ra", "ingest", "--label", "26.3"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print(f"ingest 退出码 {result.returncode}")
for line in (result.stdout or "").splitlines():
    if "台账漂移" in line or "->" in line:
        print(f"  {line}")
