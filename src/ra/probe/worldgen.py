"""世界生成事实源的探测。

两侧都探，不只取一侧。判据：两者都有则双路对账，不一致 → 报差异。
实测两版各自只有一侧：

| 版本 | 数据包 `worldgen/` | `reports/` 内 worldgen |
|---|---|---|
| 26.3 | 17 个子目录 | 不存在（`--reports` 只导出 `biome_parameters`） |
| 1.18.2 | 不存在 | 11 个子目录 |

因此对账在本期两版都不触发，但逻辑必须存在：未来某版两侧都有时，
静默取数据包会掩盖「数据包缺文件却注册成功」这类异常。
"""

from __future__ import annotations

from pathlib import Path

from .profile import Profile

# 两侧子目录名的对应关系。数据包用 `feature`/`carver`/`structure`，
# 运行期导出用 `configured_feature`/`configured_carver`/`configured_structure_feature`。
WORLDGEN_SUBDIR_ALIASES = {
    "configured_feature": "feature",
    "configured_carver": "carver",
    "configured_structure_feature": "structure",
}

__all__ = ["WORLDGEN_SUBDIR_ALIASES", "probe_worldgen"]


def _ids_under(directory: Path) -> set[str]:
    return {
        p.relative_to(directory).with_suffix("").as_posix()
        for p in directory.rglob("*.json")
    }


def _positive(counts: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in counts.items() if v}


def _from_datapack(data_root: Path) -> list[tuple[str, str, set[str]]]:
    """数据包侧的 `(命名空间, 子目录, ID 集合)` 列表。"""
    found: list[tuple[str, str, set[str]]] = []
    for ns_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        wg = ns_dir / "worldgen"
        if not wg.is_dir():
            continue
        for sub in sorted(p for p in wg.iterdir() if p.is_dir()):
            ids = _ids_under(sub)
            if ids:
                found.append((ns_dir.name, sub.name, ids))
    return found


def _from_reports(reports_root: str) -> list[tuple[str, set[str]]]:
    """运行期导出侧的 `(子目录, ID 集合)` 列表。

    导出布局随版本变过，三种候选位置逐个试，取第一个有内容的。
    """
    if not reports_root:
        return []
    for base in (
        Path(reports_root) / "worldgen" / "minecraft" / "worldgen",
        Path(reports_root) / "minecraft" / "worldgen",
        Path(reports_root) / "worldgen",
    ):
        if not base.is_dir():
            continue
        found: list[tuple[str, set[str]]] = []
        for sub in sorted(p for p in base.iterdir() if p.is_dir()):
            ids = _ids_under(sub)
            if ids:
                found.append((sub.name, ids))
        if found:
            return found
    return []


def _crosscheck(
    datapack: list[tuple[str, str, set[str]]],
    reports: list[tuple[str, set[str]]],
    profile: Profile,
) -> None:
    """两路都有时的对账。

    **不对称处理**，因为两侧的完整性含义不同：

    - 数据包是源文件全集，运行期导出只含注册成功的条目 → 数据包多是正常的
    - **运行期有而数据包没有**才是异常：说明注册表里有条目但源文件缺失

    子目录名先按别名表归一，再比对。
    """
    by_sub: dict[str, set[str]] = {}
    for _, sub, ids in datapack:
        by_sub.setdefault(sub, set()).update(ids)

    anomalies: list[str] = []
    for sub, ids in reports:
        key = WORLDGEN_SUBDIR_ALIASES.get(sub, sub)
        local = by_sub.get(key)
        if local is None:
            profile.notes.append(
                f"运行期导出的 worldgen/{sub} 在数据包里没有同名子目录"
                f"（{len(ids)} 条，可能改名或迁到别的注册表）"
            )
            continue
        only_reports = ids - local
        if only_reports:
            sample = "、".join(sorted(only_reports)[:3])
            anomalies.append(f"{sub}: {len(only_reports)} 条仅见于运行期导出（{sample}）")

    if anomalies:
        profile.add_unresolved("世界生成双路不一致：" + "；".join(anomalies))
    else:
        profile.notes.append("世界生成双路对账通过（运行期导出的每条都能在数据包里找到）")


def _anchors(entries: list[tuple[str | None, str, set[str]]]) -> dict[str, set[str]]:
    """把来源列表折成 `{worldgen/<子目录>: ID 集合}` 的锚点表。"""
    anchors: dict[str, set[str]] = {}
    for _, sub, ids in entries:
        anchors.setdefault(f"worldgen/{sub}", set()).update(ids)
    return anchors


def probe_worldgen(data_root: Path, profile: Profile) -> dict[str, set[str]]:
    """定位世界生成事实源，并顺带产出世界生成锚点。

    锚点键名用 `worldgen/<子目录>`，这样 `tags/worldgen/biome` 能凭目录名直接锚定。
    """
    datapack = _from_datapack(data_root)
    reports = _from_reports(profile.reports_root)

    if datapack and reports:
        _crosscheck(datapack, reports, profile)
        profile.worldgen_source = "datapack"
        profile.worldgen_counts = _positive(
            {f"{ns}/{sub}": len(ids) for ns, sub, ids in datapack}
        )
        return _anchors(datapack)

    if datapack:
        profile.worldgen_source = "datapack"
        profile.worldgen_counts = _positive(
            {f"{ns}/{sub}": len(ids) for ns, sub, ids in datapack}
        )
        profile.notes.append(
            "运行期导出不含 worldgen（该版 --reports 已不再导出），世界生成只来自数据包"
        )
        return _anchors(datapack)

    if reports:
        profile.worldgen_source = "reports"
        profile.worldgen_counts = {f"reports/{sub}": len(ids) for sub, ids in reports}
        profile.notes.append("世界生成不在数据包里，改用运行期导出")
        return _anchors([(None, sub, ids) for sub, ids in reports])

    profile.worldgen_source = "none"
    profile.add_unresolved("世界生成事实不可得，world/seeds 族将全部为 UNKNOWN")
    return {}
