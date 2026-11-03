"""从服务端 jar 内层派生数据包。

数据包是**派生品**，不是用户输入。实测依据（26.3）：

- 内层 jar 的 `data/` 与源码树 `resources/data` 中，除结构模板外 8373 个文件逐一同名同路径
- 结构模板两侧差 1511 个：jar 是二进制 `.nbt`（完好），源码树是 `.snbt`（palette 被抹空）

因此 `data/` 由本模块从 jar 解出，省掉用户提供一份重复的 49 MB 目录。
结构模板不在此列——它们由 `structures.py` 转成 SNBT 单独管理，避免与数据包适配器撞车。
"""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import InputError
from ..paths import pack_data, pack_jar
from ..util.hashing import sha256_file
from .datagen import cache_key
from .jar import inspect_jar
from .java import resolve_java
from .manifest import Manifest
from .structures import REPORTS_KEY_ARGS

MARKER_NAME = "data.json"
TEMPLATE_SUFFIXES = (".nbt", ".snbt")


@dataclass(frozen=True)
class DataSource:
    root: Path
    files: int
    jar_sha256: str
    cache_hit: bool

    def as_json(self) -> dict:
        return {"root": str(self.root), "files": self.files, "jar_sha256": self.jar_sha256}


def _find_inner_jar(manifest: Manifest, cache_root: Path) -> Path | None:
    """bundler 解出的内层 jar。与 datagen / structures 共用同一缓存目录。"""
    jar_path = pack_jar(manifest.pack_dir)
    digest = sha256_file(jar_path)
    info = inspect_jar(jar_path)
    java = resolve_java(
        manifest.resolve(manifest.java_home), info.java_version, info.java_component, manifest.label
    )
    key = cache_key(digest, java.version, REPORTS_KEY_ARGS)
    versions = cache_root / f"{jar_path.stem}-{key[:12]}" / "bundler" / "META-INF" / "versions"
    if not versions.is_dir():
        return None
    found = sorted(versions.rglob("*.jar"))
    return found[0] if found else None


def ensure_data(manifest: Manifest, cache_root: Path, *, force: bool = False) -> DataSource:
    """把内层 jar 的 `data/` 解到输入包内，供适配器读取。"""
    jar_path = pack_jar(manifest.pack_dir)
    info = inspect_jar(jar_path)
    if not info.is_bundler:
        raise InputError(f"{jar_path.name} 不是 bundler jar，无法从中取数据包")

    dest = pack_data(manifest.pack_dir)
    jar_digest = sha256_file(jar_path)
    marker = manifest.pack_dir / MARKER_NAME

    if not force and marker.is_file() and dest.is_dir():
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            recorded = {}
        files = sum(1 for p in dest.rglob("*") if p.is_file())
        if recorded.get("jar_sha256") == jar_digest and recorded.get("files") == files:
            return DataSource(dest, files, jar_digest, cache_hit=True)

    inner = _find_inner_jar(manifest, cache_root)
    if inner is None:
        raise InputError(
            f"内层 jar 未解出，无法派生数据包。先跑 `oa inputs init --label {manifest.label}`"
        )

    if dest.exists():
        shutil.rmtree(dest)
    count = 0
    with zipfile.ZipFile(inner) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            if name.startswith("data/"):
                if name.lower().endswith(TEMPLATE_SUFFIXES):
                    continue  # 模板由 structures 族从 jar 直接转，不落这里
                target = manifest.pack_dir / name
            elif name == "version.json":
                # 版本坐标是 jar 内的事实，一并派生，省掉用户准备
                target = manifest.pack_dir / "version.json"
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            count += 1

    marker.write_text(
        json.dumps({"jar_sha256": jar_digest, "files": count}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"由 jar 派生数据包：{count} 个文件 → {dest}", file=sys.stderr)
    return DataSource(dest, count, jar_digest, cache_hit=False)
