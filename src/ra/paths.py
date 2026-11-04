"""仓库内路径约定。"""

from __future__ import annotations

from pathlib import Path

_MARKERS = ("AGENTS.md", ".git")


def repo_root(start: Path | None = None) -> Path:
    """向上找仓库根，找不到则硬失败。"""
    here = (start or Path.cwd()).resolve()
    for cand in (here, *here.parents):
        if any((cand / marker).exists() for marker in _MARKERS):
            return cand
    raise RuntimeError(f"不在仓库内：{here}")


def inputs_root(root: Path) -> Path:
    return root / "inputs"


def output_root(root: Path) -> Path:
    return root / "output"


def input_pack(root: Path, label: str) -> Path:
    return inputs_root(root) / label


def manifest_file(root: Path) -> Path:
    """所有版本的配置集中在一个文件。"""
    return inputs_root(root) / "manifest.toml"


def pack_jar(pack: Path) -> Path:
    return pack / "server.jar"


def pack_java(pack: Path) -> Path:
    """独立整份反编译源码树，根下即 `net/minecraft/...`。"""
    return pack / "java"


def pack_data(pack: Path) -> Path:
    """数据包根，根下即各命名空间目录（`minecraft/`、`c/` 等）。"""
    return pack / "data"


def pack_assets(pack: Path) -> Path:
    return pack / "assets"


def pack_version_json(pack: Path) -> Path:
    return pack / "version.json"


def datapack_root(pack: Path) -> Path:
    return pack_data(pack)


def knowledge_root(root: Path) -> Path:
    """领域知识。目录名即分类，见 `knowledge/README.md`。"""
    return root / "knowledge"


def knowledge_assumptions(root: Path) -> Path:
    """分析前提。不属任何 `maps/` 分类，独居根下。"""
    return knowledge_root(root) / "assumptions.toml"


def knowledge_map(root: Path, category: str, name: str) -> Path:
    """`knowledge/maps/<分类>/<表名>.json`。

    分类是目录名，不是文件名前缀：一张表属于哪一层，看它放在哪，不看叫什么。
    """
    return knowledge_root(root) / "maps" / category / f"{name}.json"


def knowledge_exceptions(root: Path) -> Path:
    return knowledge_map(root, "exceptions", "unobtainable")


def output_dir(root: Path, label: str) -> Path:
    return output_root(root) / label


def cache_root(root: Path) -> Path:
    """datagen 与中间缓存。按内容寻址，可整目录删除后重建。"""
    return root / ".cache"
