"""探测器：把「输入长什么样」编译成 Profile。

原则：用注册表当锚点识别目录，不用版本号查目录名。
判不出来的记 UNKNOWN 并列进 `unresolved`，不猜。

本模块只做编排与三项零散的探测（版本坐标、reports 布局、模板来源）。
三大块各自成模块：

| 模块 | 探什么 |
|---|---|
| `datapack.py` | 数据目录与标签目录的注册表归属 |
| `loot.py` | 战利品方言（modern / legacy） |
| `worldgen.py` | 世界生成事实来自数据包、运行期导出，还是两侧都有 |
"""

from __future__ import annotations

from pathlib import Path

from ..inputs.manifest import Manifest
from ..inputs.reports import ReportsSource
from ..paths import pack_data, pack_version_json
from .anchors import Anchors, datapack_entries
from .common import load_json_safe
from .datapack import probe_datapack_dirs, probe_tag_dirs
from .loot import probe_loot_dialect
from .profile import OK, UNKNOWN, Profile
from .registries import Registries
from .worldgen import probe_worldgen

__all__ = ["build_profile"]


def _read_version_coords(pack_dir: Path, profile: Profile) -> None:
    """版本坐标只作记录，不作判据。缺失记 None。"""
    candidates = [
        pack_version_json(pack_dir),
        pack_dir / "version_store.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        doc = load_json_safe(path)
        if not isinstance(doc, dict):
            profile.notes.append(f"{path.name} 无法解析，版本坐标记 UNKNOWN")
            continue
        pack_version = doc.get("pack_version")
        if isinstance(pack_version, dict):
            # 26.x 拆成 major/minor；旧版只有单个整数。两种都认，缺失记 None。
            major = pack_version.get("data_major", pack_version.get("data"))
            profile.pack_data_major = major if isinstance(major, int) else None
        world = doc.get("world_version")
        profile.world_version = world if isinstance(world, int) else None
        protocol = doc.get("protocol_version")
        profile.protocol_version = protocol if isinstance(protocol, int) else None
        return
    profile.notes.append("未找到 version.json，版本坐标记 UNKNOWN（不作判据）")


def _probe_reports(reports: ReportsSource, profile: Profile) -> None:
    """认 reports 的布局：默认组件是 `items.json` 还是 `components/`。

    后者在 1.21.2 起取代前者。两种都要认，否则跨版本时组件族会整片落空。
    """
    profile.reports_kind = "datagen"
    profile.reports_root = str(reports.root)
    root = reports.root

    single = root / "items.json"
    nested = root / "minecraft" / "components" / "item"
    flat = root / "components" / "item"
    if nested.is_dir():
        profile.components_layout = "components"
        profile.components_dir = str(nested.relative_to(root))
    elif flat.is_dir():
        profile.components_layout = "components"
        profile.components_dir = str(flat.relative_to(root))
    elif single.is_file():
        profile.components_layout = "items"
        profile.components_dir = "items.json"
    else:
        profile.components_layout = UNKNOWN

    profile.datapack_capability = OK if (root / "datapack.json").is_file() else UNKNOWN
    profile.block_report = OK if (root / "blocks.json").is_file() else UNKNOWN

    # 缺失说明由 reports.notes 统一给出，这里不重复添加同一事。
    for note in reports.notes:
        if note not in profile.notes:
            profile.notes.append(note)


def _probe_template_source(structures, profile: Profile) -> None:
    """决定结构模板读哪一份。

    第一手是服务端 jar 内层的二进制模板（经 `--dev` 转成 SNBT）。反编译源码树的 `.snbt`
    是打包副本，26.3 的 palette 被抹成空串，且不是合法的 datagen 输入
    （`NbtUtils.snbtToStructure` 报 `Multiple entries with same key`）。

    反编译源码树侧仍然探测并记录，用于交叉校验目录名与文件数；只在 jar 侧不可得时才退回它，
    并把「该来源可能缺少普通方块身份」写进 notes，不静默降级。
    """
    src_dir = profile.template_dir
    src_files = profile.template_files
    profile.template_dir_src = src_dir

    if structures is not None and structures.files:
        profile.template_source = "jar"
        profile.template_root = str(structures.root)
        profile.template_dir = structures.rel_dir
        profile.template_files = structures.files
        if src_dir and src_dir != structures.rel_dir:
            profile.notes.append(
                f"模板目录名两侧不同：jar 为 {structures.rel_dir}，反编译源码树为 {src_dir}；采用 jar"
            )
        if src_files and src_files != structures.files:
            profile.notes.append(
                f"模板文件数两侧不同：jar {structures.files}，反编译源码树 {src_files}；采用 jar"
            )
        for note in structures.notes:
            if note not in profile.notes:
                profile.notes.append(note)
        return

    if src_dir:
        profile.template_source = "src"
        profile.notes.append(
            "未取得 jar 内层模板，结构事实退回反编译源码树的 .snbt；"
            "该来源可能缺少普通方块身份（palette 为空）"
        )
        return

    profile.template_source = "none"
    profile.add_unresolved("结构模板两处都不可得，结构族将全部为 UNKNOWN")


def build_profile(
    pack_dir: Path,
    manifest: Manifest,
    reports: ReportsSource,
    registries: Registries,
    structures=None,
) -> Profile:
    """跑全部探测，返回 Profile。顺序有依赖，见各行注释。"""
    profile = Profile(
        label=manifest.label,
        content_commit=manifest.content_commit,
        source_repo=str(manifest.source_repo) if manifest.source_repo else None,
    )

    _read_version_coords(pack_dir, profile)
    profile.registry_counts = registries.counts()
    _probe_reports(reports, profile)

    data_root = pack_data(pack_dir)
    # 目录归属要先于模板：模板目录是「全 SNBT」这条形状规则判出来的
    probe_datapack_dirs(data_root, profile)
    _probe_template_source(structures, profile)
    # 方言判定要用 loot_table 的目录归属，因此在 probe_datapack_dirs 之后
    probe_loot_dialect(data_root, profile)
    worldgen_anchors = probe_worldgen(data_root, profile)

    # 锚点要在目录扫描之后建：数据包驱动的注册表靠目录本身锚定。
    namespace = profile.namespaces[0] if profile.namespaces else "minecraft"
    pack_anchors = datapack_entries(data_root, namespace, ("datapacks",))
    pack_anchors.update(worldgen_anchors)
    anchors = Anchors(registries, pack_anchors)
    probe_tag_dirs(data_root, anchors, profile)

    for required in ("recipe", "loot_table"):
        if required not in profile.dirs:
            profile.add_unresolved(f"未定位 {required} 目录")

    return profile
