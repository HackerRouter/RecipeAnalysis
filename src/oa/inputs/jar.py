"""读取 jar：识别 bundler 外壳与传统 jar，给出可启动的 classpath。

26.x 与 1.18.2 的服务端 jar 都是 bundler 外壳（`Main-Class: net.minecraft.bundler.Main`），
内部自含两类制品，**不需要联网、不需要启动器 libraries**：

```
META-INF/versions.list   <sha256>\t<id>\t<相对 META-INF/versions 的路径>
META-INF/libraries.list  <sha256>\t<坐标>\t<相对 META-INF/libraries 的路径>
META-INF/main-class      服务端主类（不是 datagen 主类）
version.json             java_component / java_version
```

datagen 主类 `net.minecraft.data.Main` 在 versions 里的那个 server jar 中，
所以要自己组 classpath 后 `-cp ... net.minecraft.data.Main`，不能 `-jar`。
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import InputError

DATAGEN_MAIN = "net.minecraft.data.Main"

BUNDLER_MANIFEST_KEYS = ("Bundler-Format", "Main-Class")
BUNDLER_MAIN_CLASS = "net.minecraft.bundler.Main"

VERSIONS_LIST = "META-INF/versions.list"
LIBRARIES_LIST = "META-INF/libraries.list"
VERSIONS_DIR = "META-INF/versions"
LIBRARIES_DIR = "META-INF/libraries"


@dataclass(frozen=True)
class BundlerEntry:
    sha256: str
    coords: str
    path: str


@dataclass(frozen=True)
class JarInfo:
    path: Path
    is_bundler: bool
    main_class: str | None
    java_component: str | None
    java_version: int | None
    versions: tuple[BundlerEntry, ...]
    libraries: tuple[BundlerEntry, ...]

    def as_json(self) -> dict:
        return {
            "is_bundler": self.is_bundler,
            "main_class": self.main_class,
            "java_component": self.java_component,
            "java_version": self.java_version,
            "versions": len(self.versions),
            "libraries": len(self.libraries),
        }


def _parse_list(text: str) -> tuple[BundlerEntry, ...]:
    entries: list[BundlerEntry] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 3:
            raise InputError(f"bundler 清单行无法解析：{line!r}")
        entries.append(BundlerEntry(sha256=parts[0], coords=parts[1], path=parts[2]))
    return tuple(entries)


def read_manifest(archive: zipfile.ZipFile) -> dict[str, str]:
    try:
        raw = archive.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
    except KeyError:
        return {}
    manifest: dict[str, str] = {}
    # 续行以单个空格开头，接上一行的值
    key = None
    for line in raw.splitlines():
        if line.startswith(" ") and key is not None:
            manifest[key] += line[1:]
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        manifest[key] = value.strip()
    return manifest


def inspect_jar(path: Path) -> JarInfo:
    if not path.is_file():
        raise InputError(f"jar 不存在：{path}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        manifest = read_manifest(archive)

        is_bundler = (
            manifest.get("Main-Class") == BUNDLER_MAIN_CLASS
            or "Bundler-Format" in manifest
            or VERSIONS_LIST in names
        )

        java_component = None
        java_version = None
        if "version.json" in names:
            import json

            try:
                doc = json.loads(archive.read("version.json").decode("utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise InputError(f"{path} 的 version.json 无法解析：{exc}") from exc
            if isinstance(doc, dict):
                java_component = doc.get("java_component")
                version = doc.get("java_version")
                java_version = version if isinstance(version, int) else None

        versions: tuple[BundlerEntry, ...] = ()
        libraries: tuple[BundlerEntry, ...] = ()
        if VERSIONS_LIST in names:
            versions = _parse_list(archive.read(VERSIONS_LIST).decode("utf-8-sig"))
        if LIBRARIES_LIST in names:
            libraries = _parse_list(archive.read(LIBRARIES_LIST).decode("utf-8-sig"))

        if is_bundler and not versions:
            raise InputError(f"{path} 是 bundler 但 {VERSIONS_LIST} 为空")

        return JarInfo(
            path=path,
            is_bundler=is_bundler,
            main_class=manifest.get("Main-Class"),
            java_component=java_component,
            java_version=java_version,
            versions=versions,
            libraries=libraries,
        )


def extract_bundler(info: JarInfo, dest: Path) -> None:
    """解出 versions 与 libraries，只解清单里列出的条目，不整包含无关文件。"""
    if not info.is_bundler:
        return
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {f"{VERSIONS_DIR}/{e.path}" for e in info.versions}
    wanted |= {f"{LIBRARIES_DIR}/{e.path}" for e in info.libraries}
    with zipfile.ZipFile(info.path) as archive:
        present = set(archive.namelist())
        missing = sorted(wanted - present)
        if missing:
            raise InputError(
                f"{info.path.name} 缺少清单声明的 {len(missing)} 个条目，"
                f"首个：{missing[0]}"
            )
        for name in sorted(wanted):
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, target.open("wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)


def classpath(info: JarInfo, work: Path) -> list[str]:
    """datagen 的 classpath：versions 里的 server jar 排第一，其余是 libraries。"""
    if not info.is_bundler:
        return [str(info.path)]
    entries = [str(work / VERSIONS_DIR / e.path) for e in info.versions]
    entries += [str(work / LIBRARIES_DIR / e.path) for e in info.libraries]
    missing = [e for e in entries if not Path(e).is_file()]
    if missing:
        raise InputError(f"classpath 缺少 {len(missing)} 个文件，首个：{missing[0]}")
    return entries
