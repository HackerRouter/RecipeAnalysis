"""运行期导出（reports）的定位与 provenance。

reports 是 `net.minecraft.data.Main --reports` 的产物，数据包里没有这四项：
`registries.json`、默认组件报告、`blocks.json`、`datapack.json`。

本项目不保存 Mojang 制品：reports 从输入包的 jar 现场跑出来，缓存按 jar 摘要失效。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..paths import pack_jar
from ..util.hashing import sha256_file
from .datagen import DatagenResult, run_datagen
from .manifest import Manifest

PROVENANCE_FILES = ("registries.json", "blocks.json", "datapack.json")


@dataclass(frozen=True)
class ReportsSource:
    root: Path
    digests: dict[str, str]
    java: dict
    cache_hit: bool
    jar_sha256: str
    notes: tuple[str, ...]

    def as_json(self) -> dict:
        return {
            "root": str(self.root),
            "digests": self.digests,
            "java": self.java,
            "cache_hit": self.cache_hit,
            "jar_sha256": self.jar_sha256,
            "notes": list(self.notes),
        }


def collect(reports: Path) -> dict[str, str]:
    return {
        name: sha256_file(reports / name)
        for name in PROVENANCE_FILES
        if (reports / name).is_file()
    }


def ensure_reports(
    manifest: Manifest,
    cache_root: Path,
    *,
    force: bool = False,
    prefer_reports: Path | None = None,
) -> ReportsSource:
    """确保 reports 存在：没有就跑 datagen，有就复用。

    reports 一律经由 jar 得到，因此 provenance 只需 jar 摘要 + Java 版本即可复算。
    """
    result: DatagenResult = run_datagen(
        pack_jar(manifest.pack_dir),
        cache_root,
        java_home=manifest.resolve(manifest.java_home),
        label=manifest.label,
        prefer_reports=prefer_reports,
        force=force,
    )

    notes: list[str] = []
    if not (result.reports_dir / "datapack.json").is_file():
        notes.append("无 datapack.json（1.21.2 起才有该报告），数据包能力表降级")
    if not (result.reports_dir / "minecraft" / "components" / "item").is_dir() and not (
        result.reports_dir / "items.json"
    ).is_file():
        notes.append("无默认组件报告（1.20.5 引入组件系统后才有）")

    return ReportsSource(
        root=result.reports_dir,
        digests=collect(result.reports_dir),
        java=result.java.as_json(),
        cache_hit=result.cache_hit,
        jar_sha256=result.jar_digest,
        notes=tuple(notes),
    )
