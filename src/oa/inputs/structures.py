"""结构模板的第一手来源：服务端 jar 内层的二进制模板。

**为什么需要它**：`src/` 来自 `git archive <内容提交> src/main`，其中的 `.snbt`
在 26.3 的 palette 上被抹成了空串（20791 项全为 `""`，且没有 `DataVersion`），
只有方块实体的 `nbt.id` 还保留身份。那份文本甚至不是合法的 datagen 输入——
交给 `--server --input` 会在 `NbtUtils.snbtToStructure` 报
`Multiple entries with same key`。

第一手是服务端 jar 内层的 `data/<ns>/<模板目录>/**/*.nbt`：palette 是
`{id, properties}`（26.3）或 `Name`/`Properties`（1.18.2）的 compound，
方块身份完整。取法两步：

1. 从 bundler 解出的内层 jar 提取模板 `.nbt`
2. `net.minecraft.data.Main --dev --input <含 data/ 的根>` 转成 `.snbt`

第二步不自己写 NBT 解析：`--dev` 顺带做了 `DataFixTypes.STRUCTURE` 升级与
`NbtUtils.packBlockState`，自己解要额外处理新旧键名差异。

缓存目录与 `--reports` 共用（同一个 jar 摘要与 Java 大版本），因此 `bundler/`
只解一次；模板产物放在该目录的 `structures/` 子目录，按 jar 摘要失效。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import InputError
from ..paths import pack_jar
from ..util.hashing import sha256_file
from ..util.jsonio import write_json
from .datagen import cache_key
from .jar import DATAGEN_MAIN, VERSIONS_DIR, classpath, extract_bundler, inspect_jar
from .java import resolve_java
from .manifest import Manifest

MARKER_NAME = ".structures.json"
ROOT_DIRNAME = "structures"
INPUT_DIRNAME = "structures-input"
LOG_NAME = "structures.log"
TEMPLATE_SUFFIX = ".nbt"
OUTPUT_SUFFIX = ".snbt"
DEV_ARGS = ("--dev",)

# 与 --reports 共用缓存键，从而共用同一缓存目录与 bundler 解包结果。
REPORTS_KEY_ARGS = ("--reports",)


@dataclass(frozen=True)
class StructuresSource:
    """转换后的模板根，形如 `<root>/data/<ns>/<目录>/*.snbt`。"""

    root: Path
    rel_dir: str
    files: int
    jar_sha256: str
    java: dict
    cache_hit: bool
    log_path: Path
    notes: tuple[str, ...] = ()

    def as_json(self) -> dict:
        return {
            "root": str(self.root),
            "dir": self.rel_dir,
            "files": self.files,
            "jar_sha256": self.jar_sha256,
            "java": self.java,
            "cache_hit": self.cache_hit,
            "log": str(self.log_path),
            "notes": list(self.notes),
        }


def locate_template_dir(names: list[str]) -> tuple[str, int] | None:
    """在内层 jar 的文件名里找「全是模板」的目录。

    判据是内容形状而不是目录名：`structure/` 与 `structures/` 都能命中。
    代码目录（`data/<ns>/<sub>/<sub2>/...`）里混着 `.json`，不满足「全是 `.nbt`」。
    """
    buckets: dict[str, list[str]] = {}
    for name in names:
        if name.endswith("/"):
            continue
        parts = name.split("/")
        if len(parts) < 4 or parts[0] != "data":
            continue
        buckets.setdefault(f"{parts[1]}/{parts[2]}", []).append(name)

    candidates = [
        (rel, len(files))
        for rel, files in buckets.items()
        if all(f.endswith(TEMPLATE_SUFFIX) for f in files)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[1], item[0]))
    if len(candidates) > 1 and candidates[0][1] == candidates[1][1]:
        # 并列最多说明判据不足，不静默挑一个
        raise InputError(
            "内层 jar 里有多个等量的全 .nbt 目录，无法判定模板目录："
            + ", ".join(f"{rel}({count})" for rel, count in candidates[:4])
        )
    return candidates[0]


def _inner_jar(work: Path, info) -> Path:
    if not info.versions:
        raise InputError(f"{info.path.name} 没有 versions 条目，无法定位内层 jar")
    return work / VERSIONS_DIR / info.versions[0].path


def _extract(inner: Path, rel_dir: str, dest_root: Path) -> int:
    """把 `data/<rel_dir>/**/*.nbt` 解到 `dest_root/data/<rel_dir>/`，返回文件数。"""
    prefix = f"data/{rel_dir}/"
    count = 0
    with zipfile.ZipFile(inner) as archive:
        for name in archive.namelist():
            if name.endswith("/") or not name.startswith(prefix):
                continue
            if not name.endswith(TEMPLATE_SUFFIX):
                continue
            target = dest_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    return count


def _convert(
    java,
    classpath_entries: list[str],
    input_root: Path,
    output_root: Path,
    cwd: Path,
    log_path: Path,
) -> None:
    """`--dev`：读 `.nbt`，按 `DataFixTypes.STRUCTURE` 升级后写成 `.snbt`。"""
    cmd = [
        str(java.path),
        "-cp",
        os.pathsep.join(classpath_entries),
        DATAGEN_MAIN,
        *DEV_ARGS,
        "--input",
        str(input_root),
        "--output",
        str(output_root),
    ]
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        proc = subprocess.run(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise InputError(
            f"模板转换失败（exit {proc.returncode}），日志：{log_path}\n"
            f"最后几行：\n{_tail(log_path)}"
        )


def _tail(path: Path, lines: int = 15) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "（无日志）"
    return "\n".join(text[-lines:])


def _load_marker(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return doc if isinstance(doc, dict) else {}


def ensure_structures(
    manifest: Manifest,
    cache_root: Path,
    *,
    force: bool = False,
) -> StructuresSource:
    """确保内层 jar 的模板已转成 `.snbt`；命中缓存时直接复用。"""
    jar_path = pack_jar(manifest.pack_dir)
    info = inspect_jar(jar_path)
    if not info.is_bundler:
        raise InputError(
            f"{jar_path.name} 不是 bundler jar，无法从中取模板。\n"
            "请提供服务端 jar"
        )

    jar_digest = sha256_file(jar_path)
    java = resolve_java(
        manifest.resolve(manifest.java_home), info.java_version, info.java_component, manifest.label
    )

    # 与 --reports 共用目录，bundler 只解一次
    reports_key = cache_key(jar_digest, java.version, REPORTS_KEY_ARGS)
    cache_dir = cache_root / f"{jar_path.stem}-{reports_key[:12]}"
    work = cache_dir / "bundler"
    root = cache_dir / ROOT_DIRNAME
    marker = cache_dir / MARKER_NAME
    log_path = cache_dir / LOG_NAME

    inner = _inner_jar(work, info)
    recorded = _load_marker(marker)
    rel_dir = recorded.get("dir")
    if not force and isinstance(rel_dir, str) and recorded.get("jar_sha256") == jar_digest:
        produced = root / "data" / Path(rel_dir)
        files = sum(1 for p in produced.rglob(f"*{OUTPUT_SUFFIX}") if p.is_file()) if produced.is_dir() else 0
        if files and files == recorded.get("files"):
            return StructuresSource(
                root=root,
                rel_dir=rel_dir,
                files=files,
                jar_sha256=jar_digest,
                java=java.as_json(),
                cache_hit=True,
                log_path=log_path,
                notes=tuple(recorded.get("notes") or ()),
            )

    if not inner.is_file():
        print(f"解出 bundler 制品 → {work}", file=sys.stderr)
        extract_bundler(info, work)

    with zipfile.ZipFile(inner) as archive:
        located = locate_template_dir(archive.namelist())
    if located is None:
        raise InputError(
            f"{inner.name} 里没有全 {TEMPLATE_SUFFIX} 的模板目录，"
            "结构事实将无第一手来源"
        )
    rel_dir, expected = located

    if force and root.exists():
        shutil.rmtree(root)
    input_root = cache_dir / INPUT_DIRNAME
    if input_root.exists():
        shutil.rmtree(input_root)
    out_root = cache_dir / "structures-out"
    if out_root.exists():
        shutil.rmtree(out_root)

    extracted = _extract(inner, rel_dir, input_root)
    if extracted != expected:
        raise InputError(
            f"模板提取数量与 jar 清单不一致：解出 {extracted}，清单 {expected}（{rel_dir}）"
        )

    print(
        f"转换模板（Java {java.version}）：{extracted} 个 .nbt → .snbt，目录 data/{rel_dir}",
        file=sys.stderr,
    )
    _convert(java, classpath(info, work), input_root, out_root, cache_dir, log_path)

    produced = out_root / "data" / Path(rel_dir)
    files = sum(1 for p in produced.rglob(f"*{OUTPUT_SUFFIX}") if p.is_file()) if produced.is_dir() else 0
    if files != extracted:
        raise InputError(
            f"模板转换不完整：输入 {extracted} 个 .nbt，产出 {files} 个 .snbt，日志：{log_path}\n"
            f"{_tail(log_path)}"
        )

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    shutil.move(str(out_root / "data"), str(root / "data"))
    # 中间态不保留：从 jar 摘要可完整复算，留着只是占盘
    shutil.rmtree(input_root, ignore_errors=True)
    shutil.rmtree(out_root, ignore_errors=True)

    notes = ("模板来自服务端 jar 内层的二进制模板，已用 --dev 升级并转成 SNBT",)
    write_json(
        marker,
        {
            "jar_sha256": jar_digest,
            "java": java.as_json(),
            "dir": rel_dir,
            "files": files,
            "args": list(DEV_ARGS),
            "source": "jar",
            "notes": list(notes),
        },
    )
    return StructuresSource(
        root=root,
        rel_dir=rel_dir,
        files=files,
        jar_sha256=jar_digest,
        java=java.as_json(),
        cache_hit=False,
        log_path=log_path,
        notes=notes,
    )
