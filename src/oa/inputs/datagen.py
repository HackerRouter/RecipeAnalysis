"""跑 jar 的 datagen，产出 reports。

这是「从空项目能用」的关键：输入只有一个 jar，reports 由本模块跑出来，
不依赖任何预先准备好的导出，也不需要联网（bundler 自含 libraries）。

缓存键 = jar sha256 + datagen 主类 + 参数 + Java 大版本。
缓存命中时直接复用，不重跑；reports 内容地址化，下游按摘要判失效。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..errors import InputError
from ..util.hashing import sha256_file
from ..util.jsonio import write_json
from .java import JavaRuntime, resolve_java
from .jar import DATAGEN_MAIN, JarInfo, classpath, extract_bundler, inspect_jar

CACHE_MARKER = ".datagen.json"
REPORTS_DIRNAME = "reports"
LOG_NAME = "datagen.log"


@dataclass(frozen=True)
class DatagenResult:
    reports_dir: Path
    cache_hit: bool
    jar_digest: str
    java: JavaRuntime
    log_path: Path

    def as_json(self) -> dict:
        return {
            "reports_dir": str(self.reports_dir),
            "cache_hit": self.cache_hit,
            "jar_sha256": self.jar_digest,
            "java": self.java.as_json(),
            "log": str(self.log_path),
        }


def cache_key(jar_digest: str, java_major: int, args: tuple[str, ...]) -> str:
    """缓存键：同一 jar 与同一 Java 大版本、同一组参数下复用产物。

    structures 模块用 `("--reports",)` 这一组键定位同一个缓存目录，
    以便复用 `bundler/` 的解包结果，同时把自己的产物放在子目录里。
    """
    import hashlib

    payload = json.dumps(
        {"jar": jar_digest, "java": java_major, "main": DATAGEN_MAIN, "args": list(args)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _expected_reports() -> tuple[str, ...]:
    """四项必备产物。缺任一项视为 datagen 失败，不静默接受半成品。"""
    return ("registries.json", "blocks.json")


def _validate_reports(reports: Path) -> list[str]:
    missing = [name for name in _expected_reports() if not (reports / name).is_file()]
    if missing:
        raise InputError(f"datagen 产物不完整，缺 {', '.join(missing)}：{reports}")
    notes: list[str] = []
    if not (reports / "datapack.json").is_file():
        notes.append("无 datapack.json（1.21.2 起才有该报告）")
    if not (reports / "minecraft" / "components" / "item").is_dir() and not (
        reports / "items.json"
    ).is_file():
        notes.append("无默认组件报告（1.20.5 引入组件系统后才有）")
    return notes


def run_datagen(
    jar_path: Path,
    cache_root: Path,
    *,
    java_home: Path | None = None,
    label: str = "",
    prefer_reports: Path | None = None,
    force: bool = False,
) -> DatagenResult:
    info = inspect_jar(jar_path)
    jar_digest = sha256_file(jar_path)

    if not info.is_bundler:
        raise InputError(
            f"{jar_path.name} 不是 bundler jar，本期未实现传统 jar 的依赖装配。\n"
            "请提供官方服务端 jar（内含 META-INF/versions.list）"
        )

    java = resolve_java(java_home, info.java_version, info.java_component, label)

    args = ("--reports",)
    key = cache_key(jar_digest, java.version, args)
    cache_dir = cache_root / f"{jar_path.stem}-{key[:12]}"
    marker = cache_dir / CACHE_MARKER
    reports = cache_dir / REPORTS_DIRNAME

    if not force and marker.is_file() and reports.is_dir():
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            recorded = {}
        if recorded.get("key") == key:
            _validate_reports(reports)
            return DatagenResult(
                reports_dir=reports,
                cache_hit=True,
                jar_digest=jar_digest,
                java=java,
                log_path=cache_dir / LOG_NAME,
            )

    if prefer_reports is not None and prefer_reports.is_dir() and not force:
        # 用户已给出导出：仍复制进缓存，保证 provenance 单点、可复算
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(prefer_reports, reports)
        notes = _validate_reports(reports)
        write_json(
            marker,
            {
                "key": key,
                "jar_sha256": jar_digest,
                "java": java.as_json(),
                "args": list(args),
                "source": "provided",
                "notes": notes,
            },
        )
        return DatagenResult(
            reports_dir=reports,
            cache_hit=False,
            jar_digest=jar_digest,
            java=java,
            log_path=cache_dir / LOG_NAME,
        )

    work = cache_dir / "bundler"
    if force and cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"解出 bundler 制品 → {work}", file=sys.stderr)
    extract_bundler(info, work)
    cp = classpath(info, work)

    out_dir = cache_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(java.path), "-cp", os.pathsep.join(cp), DATAGEN_MAIN, *args, "--output", str(out_dir)]
    print(f"运行 datagen（Java {java.version}）：{DATAGEN_MAIN} {' '.join(args)}", file=sys.stderr)

    log_path = cache_dir / LOG_NAME
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        proc = subprocess.run(cmd, cwd=str(cache_dir), stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise InputError(
            f"datagen 失败（exit {proc.returncode}），日志：{log_path}\n"
            f"最后几行：\n{_tail(log_path)}"
        )

    produced = out_dir / REPORTS_DIRNAME
    if not produced.is_dir():
        raise InputError(f"datagen 未产出 reports 目录，日志：{log_path}\n{_tail(log_path)}")
    if reports.exists():
        shutil.rmtree(reports)
    shutil.move(str(produced), str(reports))

    notes = _validate_reports(reports)
    write_json(
        marker,
        {
            "key": key,
            "jar_sha256": jar_digest,
            "java": java.as_json(),
            "args": list(args),
            "source": "datagen",
            "notes": notes,
        },
    )
    return DatagenResult(
        reports_dir=reports,
        cache_hit=False,
        jar_digest=jar_digest,
        java=java,
        log_path=log_path,
    )


def _tail(path: Path, lines: int = 25) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "（日志不可读）"
    return "\n".join(content[-lines:])
