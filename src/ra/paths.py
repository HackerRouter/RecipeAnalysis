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


def pack_datapacks(pack: Path) -> Path:
    """外来数据包目录。每项是一个含 `pack.mcmeta` 的目录或 `.zip`。"""
    return pack / "datapacks"


def pack_datapack_merged(pack: Path) -> Path:
    """覆盖合并结果暂存根。根下 `data/` 即生效数据根。"""
    return pack / "datapack-merged"


def pack_data_merged(pack: Path) -> Path:
    """生效数据根（合并结果侧）。没有数据包时该目录不存在。"""
    return pack_datapack_merged(pack) / "data"


def pack_pack_meta(pack: Path) -> Path:
    """原版数据包的 `pack.mcmeta`，从内层 jar 派生，用作格式相容判据。"""
    return pack / "pack.mcmeta"


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


# 渲染件子目录名。`ra-paths` 只拿到内部表示文件，目录名从这一个常量取。
PATHS_DIR = "paths"


def output_profile(root: Path, label: str) -> Path:
    """探测结论 `profile.json`：这一版输入长什么样，与 `guide.md` 同在产物根上。"""
    return output_dir(root, label) / "profile.json"


def output_facts(root: Path, label: str) -> Path:
    """事实库：每族一份 `<种类>.jsonl`，加台账 `ledger.jsonl` 与汇总 `summary.json`。"""
    return output_dir(root, label) / "facts"


def output_report(root: Path, label: str) -> Path:
    """求解结论：可达性、覆盖率、`run.json` 与缺口/工具要求明细。"""
    return output_dir(root, label) / "report"


def output_export(root: Path, label: str) -> Path:
    """下游可直接查的表（`ra export` 生成）。下游只读这一目录。"""
    return output_dir(root, label) / "export"


def output_paths(root: Path, label: str) -> Path:
    """`ra-paths` 的渲染件目录：每个物品一组 `.dot/.svg/.html`。

    渲染件只是内部表示派生出的视图，与 `graph.json` 分开放：内部表示是核心产物，
    视图可以换参数反复重画，混在产物根上会让目录被几十份副本淹没。
    """
    return output_dir(root, label) / PATHS_DIR


def cache_root(root: Path) -> Path:
    """datagen 与中间缓存。按内容寻址，可整目录删除后重建。"""
    return root / ".cache"
