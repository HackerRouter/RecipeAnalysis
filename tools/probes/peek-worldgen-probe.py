"""打印两版 Profile 的世界生成部分与相关 note。"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from oa.inputs import ensure_reports, load_manifest
from oa.paths import cache_root, input_pack, repo_root
from oa.probe import build_profile
from oa.probe.registries import Registries

ROOT = repo_root()
OUT = Path("output/worldgen-probe.txt")
lines: list[str] = []

for label in ("26.3", "1.18.2"):
    pack = input_pack(ROOT, label)
    if not (pack / "manifest.toml").is_file():
        lines.append(f"=== {label}: 无输入包")
        continue
    manifest = load_manifest(pack)
    reports = ensure_reports(manifest, cache_root(ROOT))
    registries = Registries.load(reports.root / "registries.json")
    p = build_profile(pack, manifest, reports, registries)

    lines.append(f"=== {label}")
    lines.append(f"  worldgen_source = {p.worldgen_source}")
    lines.append(f"  worldgen_counts = {p.worldgen_counts}")
    lines.append(f"  unresolved = {p.unresolved}")
    wg_notes = [n for n in p.notes if "世界生成" in n or "worldgen" in n]
    lines.append(f"  相关 note ({len(wg_notes)}):")
    for note in wg_notes:
        lines.append(f"    - {note}")
    lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
