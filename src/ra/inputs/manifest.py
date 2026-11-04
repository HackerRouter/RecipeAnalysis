"""输入配置：`inputs/manifest.toml`，一个文件管所有版本。

一个版本 = `inputs/<label>/` 一个目录。第一手只有两样，其余是派生品：

```
inputs/
  manifest.toml          ← 全部版本的配置（本模块维护）
  <label>/
    server.jar           第一手：服务端 jar
    java/                第一手（或由仓库导出，见下）
    data/                派生：从 jar 内层解出
    version.json         派生：从 jar 内层解出
```

配置以版本目录为准：目录在就补一段配置，配置里有但目录不在就忽略该段。
这样增删目录后不需要手改 manifest，也不会因为残留配置报错。

## 源码从哪来

源码是完整整份，但不必按版本各备一份：一份 git 仓库带着多个版本的历史是常见
组织方式。此时在顶层 `[source]` 段写仓库位置，在每个版本段写该版本对应的提交：

```toml
[source]
repo = "ref/MCDecompVers"

["26.3"]
content_commit = "c1fd2a862"
"java_home" = "..."
```

提交号必须显式给出，不推导：一个仓库的工作树只停在一个版本，HEAD 只对应其中一份
快照，拿它当某个版本的提交号会得到「看起来可信的错值」。没配 `content_commit` 的
版本则直接用手放的 `inputs/<label>/java/`，provenance 记 `null`。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import InputError
from ..paths import inputs_root, manifest_file, repo_root

MANIFEST_NAME = "manifest.toml"
SOURCE_SECTION = "source"


@dataclass(frozen=True)
class Manifest:
    label: str
    # 该版本在源码仓里对应的提交；未配置为 None。
    content_commit: str | None
    pack_dir: Path
    java_home: str | None = None
    # 源码仓位置（绝对路径）；未配置为 None。
    source_repo: Path | None = None
    # 源码根在仓库里的路径；一般留空由特征文件自动定位，多于一份源码树时必须写。
    source_path: str | None = None
    notes: list[str] = field(default_factory=list)

    def resolve(self, rel: str | None) -> Path | None:
        """配置里的相对路径按输入包目录解析。"""
        return None if rel is None else (self.pack_dir / rel)


def _manifest_path(pack_dir: Path) -> Path:
    """配置在 `inputs/` 根，不在版本目录里。"""
    root = pack_dir.parent
    path = manifest_file(root.parent)
    return path if path.is_file() else root / MANIFEST_NAME


def _read_sections(path: Path) -> dict[str, dict]:
    """读出所有表。顶层 `[source]` 不是版本段，由 `_read_source` 单独消费。"""
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    sections: dict[str, dict] = {}
    for key, value in raw.items():
        if key == SOURCE_SECTION:
            continue
        if isinstance(value, dict):
            sections[str(key)] = value
    return sections


def _read_source(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    value = raw.get(SOURCE_SECTION)
    return value if isinstance(value, dict) else {}


def _write_sections(path: Path, sections: dict[str, dict], source: dict) -> None:
    """重写配置。已配置的 `[source]` 必须原样写回：它不在版本段里，
    若当成提示覆盖掉，下次运行就找不到源码仓。
    """
    lines = [
        "# 每个版本一段，段名即 `inputs/<label>/` 的目录名。",
        "# 增删输入目录后本文件会由 `ra inputs init` 自动补齐，无需手改。",
        "",
        "# 源码仓库：一份仓库带多个版本的历史，各版本段用 content_commit 指明用哪个提交。",
        "# 不写这一行则要求各版本段里的 java/ 已放好完整源码树。",
    ]
    repo = source.get("repo")
    lines.append(
        f'[source]\nrepo = "{repo}"'
        if repo
        else '# [source]\n# repo = "<源码仓库路径>"'
    )
    lines.append("")
    for label in sorted(sections, key=_version_key):
        body = sections[label]
        lines.append(f'["{label}"]')
        commit = body.get("content_commit")
        lines.append(
            f'content_commit = "{commit}"'
            if commit
            else '# content_commit = "<该版本在源码仓里的提交>"'
        )
        src_path = body.get("source_path")
        if src_path:
            lines.append(f'"source_path" = "{src_path}"')
        java = body.get("java_home")
        lines.append(f'"java_home" = "{java}"' if java else '# "java_home" = "<JDK 根目录>"')
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")


def _version_key(label: str) -> tuple:
    """版本号按数值排序，非数字标签排最后。"""
    try:
        return (0, tuple(int(part) for part in label.split(".")))
    except ValueError:
        return (1, label)


# 版本段里允许出现的键。不在其中的旧键会被 `reconcile` 顺手清掉。
KNOWN_KEYS = frozenset({"java_home", "content_commit", "source_path"})


def reconcile(root: Path) -> tuple[list[str], list[str], Path]:
    """对齐版本目录与配置。

    返回 `(新增的标签, 被忽略的标签, 配置路径)`，并把结果写回文件。
    新增的段只有占位注释，需要人补 `java_home` 与 `content_commit`。
    """
    inputs = inputs_root(root)
    path = manifest_file(root)
    sections = _read_sections(path)
    source = _read_source(path)

    # `manifest.toml` 自己不是版本目录，不能当标签
    on_disk = sorted(
        (child.name for child in inputs.iterdir() if child.is_dir()),
        key=_version_key,
    ) if inputs.is_dir() else []

    added = [label for label in on_disk if label not in sections]
    ignored = sorted((label for label in sections if label not in on_disk), key=_version_key)
    stale = any(set(body) - KNOWN_KEYS for body in sections.values())

    for label in added:
        sections[label] = {}
    for label in ignored:
        del sections[label]

    if added or ignored or stale or not path.is_file():
        _write_sections(path, sections, source)
    return added, ignored, path


def _resolve_repo(root: Path, rel: object) -> Path | None:
    """`[source] repo` 按仓库根解析；给了绝对路径就用它本身。"""
    if not isinstance(rel, str) or not rel.strip():
        return None
    candidate = Path(rel)
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


def load_manifest(pack_dir: Path) -> Manifest:
    """读该版本的配置。目录存在即视为已配置，缺 `java_home` 留待导出时再报。"""
    path = _manifest_path(pack_dir)
    sections = _read_sections(path)
    source = _read_source(path)
    label = pack_dir.name
    section = sections.get(label, {})

    commit = section.get("content_commit")
    path = section.get("source_path")
    return Manifest(
        label=label,
        content_commit=str(commit) if commit else None,
        pack_dir=pack_dir,
        java_home=section.get("java_home"),
        source_repo=_resolve_repo(repo_root(pack_dir), source.get("repo")),
        source_path=path if isinstance(path, str) and path.strip() else None,
    )


def check_pack_layout(pack_dir: Path) -> None:
    """输入完整性：`java/` 源码树必须存在。

    `data/` 不检查——它由 `ensure_data` 从 jar 派生，可能尚未生成。
    `java/` 若由 `ensure_source` 从仓库导出，应在调用本函数之前就已就位。
    """
    from ..paths import pack_java

    java = pack_java(pack_dir)
    if not java.is_dir():
        raise InputError(
            f"输入包缺目录：{java}\n"
            f"二选一：配 [source] repo + 该版本段的 content_commit，"
            f"或把完整源码树放到 {java}（根下即 net/minecraft/...）。"
        )
