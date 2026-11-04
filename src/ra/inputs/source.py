"""从独立源码仓按提交导出源码树。

**为什么需要它**：源码是完整整份，但不一定要按版本各备一份。常见组织方式是一份
git 仓库带着多个版本的历史，每版本对应其中一个提交。此时用户只需在配置里指明
「哪个提交是哪个版本」，源码由本模块从仓库导出——不 checkout、不建工作树，符合
`ref/` 的只读红线。

**为什么不用自动探测 HEAD**：一个仓库的工作树只能停在一个版本，HEAD 只对应其中
一份快照。若拿 HEAD 当某个版本的提交号，得到的是「看起来可信的错值」——比记
`null` 更糟。所以提交号必须由用户显式给出。

**两种输入形态并存**：

| 配置 | 源码从哪来 |
|---|---|
| 版本段有 `content_commit` | 从 `[source] repo` 导出到 `inputs/<label>/java/` |
| 版本段无 `content_commit` | 直接用用户放在 `inputs/<label>/java/` 的现成源码树 |

后者用于手上没有 git 历史的情形，provenance 记 `null`。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..errors import InputError
from ..paths import pack_java
from .manifest import Manifest

MARKER_NAME = "java.json"

# 特征文件：用来定位源码根，不猜目录布局。
#
# 各类源码仓的布局差别很大——`src/main/java/`（Gradle）、`src/`（裸导出）、
# 根下直接 `net/`（反编译产物）、`client/src/`……列候选目录永远补不全，
# 而且新布局一出现就静默失配。改用一个每个版本都在、位置又固定的文件当锚：
# `WorldVersion.java` 自 1.18 起一直在 `net/minecraft/` 下，且这个包名不会变
# （混淆产物里它也是这个名字，它本身承载版本号语义）。
#
# 命中后取文件路径的前缀即源码根，与仓库怎么组织无关。
FEATURE_FILES = (
    "net/minecraft/WorldVersion.java",
    "net/minecraft/SharedConstants.java",
)


@dataclass(frozen=True)
class SourceTree:
    root: Path
    files: int
    commit: str | None
    source_path: str | None
    cache_hit: bool

    def as_json(self) -> dict:
        return {
            "root": str(self.root),
            "files": self.files,
            "commit": self.commit,
            "source_path": self.source_path,
        }


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    """只读调用。超时给足：`ls-tree` 在几十万文件的历史上也要几秒。"""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=600,
    )


def _treeish(commit: str, path: str | None) -> str:
    return f"{commit}:{path}" if path else commit


def find_source_paths(repo: Path, commit: str) -> list[str]:
    """用特征文件在提交里定位源码根，返回相对仓库根的路径（根目录为空串）。

    一次性读全量文件清单再找匹配，而不是逐个猜候选目录：后者漏一个就静默
    失配，前者对任何布局都成立。

    返回所有命中，去重保序。多于一个说明这个提交里有并列多份源码树，
    由调用方决定是报错还是澄清——不能静默取第一个。
    """
    proc = _git(repo, "ls-tree", "-r", "--name-only", commit)
    if proc.returncode != 0:
        raise InputError(f"读取提交 {commit} 的文件清单失败：{proc.stderr.strip()}")
    paths = proc.stdout.splitlines()

    for feature in FEATURE_FILES:
        suffix = "/" + feature
        roots: list[str] = []
        for path in paths:
            if path == feature:
                root = ""
            elif path.endswith(suffix):
                root = path[: -len(suffix)]
            else:
                continue
            if root not in roots:
                roots.append(root)
        if roots:
            return roots
    return []


def find_source_path(repo: Path, commit: str) -> str | None:
    """`find_source_paths` 的唯一结果版。多份源码树时抛错，不猜。"""
    roots = find_source_paths(repo, commit)
    if not roots:
        return None
    if len(roots) > 1:
        raise InputError(
            f"提交 {commit} 里有 {len(roots)} 份并列的源码树：\n"
            + "\n".join(f"  {root or '<根>'}" for root in roots)
            + "\n在 manifest.toml 的版本段写 source_path 指明用哪一份。"
        )
    return roots[0]


def _count_files(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file())


def _resolve_source_path(repo: Path, commit: str, configured: str | None) -> str | None:
    """源码根：配置优先；未配置则由特征文件定位。

    配置的解释权在用户——特征文件只是免去手填的便利。两者都拿不到才返回 None。
    """
    if configured is not None:
        return configured
    return find_source_path(repo, commit)


def _read_marker(pack_dir: Path) -> dict:
    marker = pack_dir / MARKER_NAME
    if not marker.is_file():
        return {}
    try:
        doc = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _extract(repo: Path, commit: str, path: str, dest: Path) -> None:
    """`git archive` 到临时 tar 再解，不经过 checkout。"""
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "src.tar"
        proc = _git(repo, "archive", "--format=tar", _treeish(commit, path), "-o", str(archive))
        if proc.returncode != 0:
            raise InputError(
                f"从 {repo} 导出提交 {commit} 的 {path} 失败：{proc.stderr.strip()}"
            )
        if not archive.is_file():
            raise InputError(f"git archive 未产出文件：{commit}:{path}")
        with tarfile.open(archive) as tar:
            # `data` 过滤器挡掉绝对路径与上跳，解开的是别人给的仓库
            tar.extractall(dest, filter="data")


def ensure_source(manifest: Manifest, *, force: bool = False) -> SourceTree:
    """保证 `inputs/<label>/java/` 就位。

    配了 `content_commit` 就从仓库导出（按提交号与仓库路径失效），否则要求用户
    已经放好源码树。两种情况都不改用户的第一手内容——导出的只是这一个目录。
    """
    dest = pack_java(manifest.pack_dir)
    commit = manifest.content_commit

    if commit is None:
        if not dest.is_dir():
            raise InputError(
                f"输入包 {manifest.label} 既没有配 content_commit，也没有 java/ 源码树。\n"
                f"二选一：\n"
                f"  1. 在 manifest.toml 的 [\"{manifest.label}\"] 段写 content_commit，"
                f"并在 [source] 段写 repo\n"
                f"  2. 直接把完整源码树放到 {dest}（根下即 net/minecraft/...）"
            )
        files = _count_files(dest)
        return SourceTree(dest, files, None, None, cache_hit=True)

    repo = manifest.source_repo
    if repo is None:
        raise InputError(
            f"版本 {manifest.label} 配了 content_commit = \"{commit}\"，"
            f"但 manifest.toml 没有 [source] 段的 repo。\n"
            f"加一段：[source]\\nrepo = \"<源码仓库路径>\""
        )
    if not (repo / ".git").exists():
        raise InputError(f"[source] repo 不是 git 仓库：{repo}")

    recorded = _read_marker(manifest.pack_dir)
    if (
        not force
        and dest.is_dir()
        and recorded.get("commit") == commit
        and recorded.get("repo") == str(repo)
    ):
        files = _count_files(dest)
        if recorded.get("files") == files:
            return SourceTree(
                dest, files, commit, recorded.get("source_path"), cache_hit=True
            )

    # 没有 marker 的 java/ 是用户手工放的第一手源码，不能当派生物覆盖掉（红线 2）。
    if dest.is_dir() and not recorded and not force:
        raise InputError(
            f"{dest} 已存在但不是本工具导出的（无 {MARKER_NAME}），视为用户的第一手源码。\n"
            f"要改用仓库导出的源码：删掉该目录，或显式加 --force 允许覆盖。"
        )

    path = _resolve_source_path(repo, commit, manifest.source_path)
    if path is None:
        raise InputError(
            f"提交 {commit} 里没找到 Java 源码树。\n"
            f"按特征文件查找（{', '.join(FEATURE_FILES)}），一个都没命中。\n"
            f"确认这个提交号对应的树里含完整源码；若源码根位置特殊，"
            f"在 manifest.toml 的版本段写 source_path 指定。"
        )

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    _extract(repo, commit, path, dest)
    files = _count_files(dest)

    (manifest.pack_dir / MARKER_NAME).write_text(
        json.dumps(
            {"repo": str(repo), "commit": commit, "source_path": path, "files": files},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return SourceTree(dest, files, commit, path, cache_hit=False)
