"""Profile：探测结果。后续所有解释器按 Profile 分派，不按版本号判断。

每条断言都带 `status`：`ok` / `unknown`。`unknown` 不是失败，是「这个版本不提供该事实」，
下游据此走降级路径或产出 UNKNOWN 节点，绝不静默当成「没有」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OK = "ok"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class DirClaim:
    """一个注册表目录的归属判定。"""

    registry: str
    path: str
    files: int
    shape: str | None
    coverage: float
    status: str = OK

    def as_json(self) -> dict:
        return {
            "registry": self.registry,
            "path": self.path,
            "files": self.files,
            "shape": self.shape,
            "coverage": round(self.coverage, 4),
            "status": self.status,
        }


@dataclass(frozen=True)
class TagDir:
    """标签子目录 → 注册表归属。"""

    registry: str
    path: str
    files: int
    coverage: float
    status: str = OK

    def as_json(self) -> dict:
        return {
            "registry": self.registry,
            "path": self.path,
            "files": self.files,
            "coverage": round(self.coverage, 4),
            "status": self.status,
        }


@dataclass
class Profile:
    label: str
    # 反编译源码树不在 git 仓库内时为 None。两者都只作 provenance，不作判据。
    content_commit: str | None
    source_repo: str | None = None

    # 版本坐标：只作记录，不作判据。缺失记 None。
    pack_data_major: int | None = None
    world_version: int | None = None
    protocol_version: int | None = None

    # 注册表
    registry_counts: dict[str, int] = field(default_factory=dict)

    # reports 布局
    reports_kind: str = "absent"
    reports_root: str | None = None
    components_layout: str = UNKNOWN
    components_dir: str | None = None
    datapack_capability: str = UNKNOWN
    block_report: str = UNKNOWN

    # 数据包目录归属
    namespaces: list[str] = field(default_factory=list)
    dirs: dict[str, DirClaim] = field(default_factory=dict)
    tag_dirs: dict[str, TagDir] = field(default_factory=dict)

    # 结构模板：第一手是服务端 jar 内层的二进制模板（转成 SNBT）。
    # `template_dir_src` 记录反编译源码树侧的探测结果，只作交叉校验；两份目录名可能不同。
    template_dir: str | None = None
    template_ext: str | None = None
    template_source: str = "none"  # jar / src / none
    template_root: str | None = None  # 含 data/ 的根，仅 jar 来源有
    template_dir_src: str | None = None
    template_files: int = 0

    # 世界生成归属：datapack / reports / both / none
    worldgen_source: str = "none"
    worldgen_counts: dict[str, int] = field(default_factory=dict)

    # 战利品方言
    loot_dialect: str = UNKNOWN
    loot_dialect_evidence: dict[str, int] = field(default_factory=dict)

    # 需要整棵排除的实验包目录
    excluded_dirs: list[str] = field(default_factory=list)

    # 探测过程中产生的注释与未决项
    notes: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def dir_for(self, registry: str) -> str | None:
        claim = self.dirs.get(registry)
        return claim.path if claim and claim.status == OK else None

    def add_unresolved(self, item: str) -> None:
        if item not in self.unresolved:
            self.unresolved.append(item)

    def as_json(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "content_commit": self.content_commit,
            "source_repo": self.source_repo,
            "version": {
                "pack_data_major": self.pack_data_major,
                "world_version": self.world_version,
                "protocol_version": self.protocol_version,
            },
            "reports": {
                "kind": self.reports_kind,
                "root": self.reports_root,
                "components_layout": self.components_layout,
                "components_dir": self.components_dir,
                "datapack_capability": self.datapack_capability,
                "block_report": self.block_report,
            },
            "registries": self.registry_counts,
            "namespaces": self.namespaces,
            "dirs": {k: v.as_json() for k, v in sorted(self.dirs.items())},
            "tag_dirs": {k: v.as_json() for k, v in sorted(self.tag_dirs.items())},
            "templates": {
                "dir": self.template_dir,
                "ext": self.template_ext,
                "source": self.template_source,
                "root": self.template_root,
                "dir_src": self.template_dir_src,
                "files": self.template_files,
            },
            "worldgen": {
                "source": self.worldgen_source,
                "counts": self.worldgen_counts,
            },
            "loot_dialect": {
                "dialect": self.loot_dialect,
                "evidence": self.loot_dialect_evidence,
            },
            "excluded_dirs": self.excluded_dirs,
            "notes": self.notes,
            "unresolved": self.unresolved,
        }
