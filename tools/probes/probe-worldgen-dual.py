"""核对两版的 worldgen 双来源：数据包 vs 运行期导出。

判据：「两者都有则双路对账，不一致 → 硬失败并报差异」。
先量出实际差异，再决定对账实现成什么强度。输出落文件，避免终端代码页乱码。
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from ra.inputs import ensure_reports, load_manifest
from ra.paths import cache_root, input_pack, repo_root

ROOT = repo_root()
OUT = Path("output/worldgen-dual.txt")
lines: list[str] = []


def ids_under(directory: Path) -> set[str]:
    return {p.relative_to(directory).with_suffix("").as_posix() for p in directory.rglob("*.json")}


for label in ("26.3", "1.18.2"):
    pack = input_pack(ROOT, label)
    if not (pack / "manifest.toml").is_file():
        lines.append(f"=== {label}: 无输入包")
        continue
    lines.append(f"=== {label}")

    manifest = load_manifest(pack)
    reports = ensure_reports(manifest, cache_root(ROOT))
    lines.append(f"  reports 根: {reports.root.relative_to(ROOT)}")

    data_root = pack / "src" / "main" / "resources" / "data"
    datapack: dict[str, set[str]] = {}
    for ns_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        wg = ns_dir / "worldgen"
        if not wg.is_dir():
            continue
        for sub in sorted(p for p in wg.iterdir() if p.is_dir()):
            datapack[sub.name] = ids_under(sub)
    lines.append(
        f"  数据包 worldgen 子目录 {len(datapack)}: "
        + ", ".join(f"{k}={len(v)}" for k, v in sorted(datapack.items()))
    )

    reports_hits: dict[str, set[str]] = {}
    for candidate in (
        reports.root / "worldgen" / "minecraft" / "worldgen",
        reports.root / "minecraft" / "worldgen",
        reports.root / "worldgen",
    ):
        if candidate.is_dir():
            for sub in sorted(p for p in candidate.iterdir() if p.is_dir()):
                reports_hits[sub.name] = ids_under(sub)
            lines.append(f"  reports 路径: {candidate.relative_to(ROOT)}")
            break
    lines.append(
        f"  reports worldgen 子目录 {len(reports_hits)}: "
        + ", ".join(f"{k}={len(v)}" for k, v in sorted(reports_hits.items()))
    )

    common = set(datapack) & set(reports_hits)
    lines.append(f"  两侧同名子目录: {sorted(common)}")
    lines.append(f"  仅数据包的子目录: {sorted(set(datapack) - set(reports_hits))}")
    lines.append(f"  仅 reports 的子目录: {sorted(set(reports_hits) - set(datapack))}")
    for sub in sorted(common):
        only_dp = datapack[sub] - reports_hits[sub]
        only_rp = reports_hits[sub] - datapack[sub]
        lines.append(
            f"    {sub:22s} 交集 {len(datapack[sub] & reports_hits[sub]):5d}"
            f"  仅数据包 {len(only_dp):4d}  仅 reports {len(only_rp):4d}"
        )
        for name in sorted(only_rp)[:5]:
            lines.append(f"        仅 reports: {name}")
    lines.append("")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"wrote {OUT}")
