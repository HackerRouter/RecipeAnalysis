"""数据包目录归属探测：数据目录与标签目录。

原则：**用注册表当锚点识别目录，不用版本号查目录名**。目录叫什么不重要，
里面装的是什么形状才重要。

数据目录按内容形状归类（配方形状、战利品形状、标签形状），
标签目录按成员与注册表条目名的重合率归属。判不出来就记 note 或 UNRESOLVED，
不猜。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from .anchors import Anchors
from .common import SHAPE_MIN, load_json_safe, sample
from .profile import OK, DirClaim, Profile, TagDir
from .shapes import (
    BLOCK_TRANSFORM,
    LOOT_TABLE,
    RECIPE,
    TAG,
    TRADE_OFFER,
    TRADE_SET,
    classify,
    resolve_dominant,
)

__all__ = ["probe_datapack_dirs", "probe_tag_dirs"]

# 形状 → 注册表名。不在表里的形状不产生目录归属。
SHAPE_REGISTRY = {
    RECIPE: "recipe",
    LOOT_TABLE: "loot_table",
    TAG: "tags",
    TRADE_OFFER: "villager_trade",
    TRADE_SET: "trade_set",
    BLOCK_TRANSFORM: "block_transformer",
}

# 整个命名空间下要整棵排除的子目录。`datapacks/` 是嵌套数据包，不是本包内容。
EXCLUDED_SUBDIR = "datapacks"


def probe_datapack_dirs(data_root: Path, profile: Profile) -> None:
    """给每个数据目录定注册表归属，并顺带记下模板目录候选。"""
    if not data_root.is_dir():
        raise FileNotFoundError(f"数据包目录不存在：{data_root}")

    namespaces = sorted(p.name for p in data_root.iterdir() if p.is_dir())
    profile.namespaces = namespaces

    template_best: tuple[str, int] | None = None

    for ns in namespaces:
        ns_dir = data_root / ns
        excluded_ns = ns_dir / EXCLUDED_SUBDIR
        if excluded_ns.is_dir():
            profile.excluded_dirs.append(f"{ns}/{EXCLUDED_SUBDIR}")

        for top in sorted(p for p in ns_dir.iterdir() if p.is_dir()):
            if top.name == EXCLUDED_SUBDIR:
                continue
            files = [f for f in top.rglob("*") if f.is_file()]
            if not files:
                continue
            rel = f"{ns}/{top.name}"

            snbt = [f for f in files if f.suffix == ".snbt"]
            if snbt and len(snbt) == len(files):
                # 全 SNBT 的目录即模板目录。`structure/` 与 `structures/` 都命中。
                if template_best is None or len(snbt) > template_best[1]:
                    template_best = (rel, len(snbt))
                continue

            jsons = [f for f in files if f.suffix == ".json"]
            if not jsons:
                profile.notes.append(f"{rel} 无非 JSON 无非 SNBT 文件，未归类")
                continue

            counts: Counter[str] = Counter()
            for path in sample(sorted(jsons)):
                counts[classify(load_json_safe(path))] += 1

            shape, ratio = resolve_dominant(counts)
            if shape is None or ratio < SHAPE_MIN:
                profile.notes.append(f"{rel} 形状不明确（{dict(counts)}），不作归属")
                continue

            registry = SHAPE_REGISTRY.get(shape)
            if registry is None:
                continue

            existing = profile.dirs.get(registry)
            claim = DirClaim(
                registry=registry,
                path=rel,
                files=len(jsons),
                shape=shape,
                coverage=ratio,
                status=OK,
            )
            # 同形状可能有多个目录（如 `recipe/` 与 `recipes/` 并存于不同版本），
            # 取文件数最多的那个。
            if existing is None or claim.files > existing.files:
                profile.dirs[registry] = claim

    if template_best is not None:
        profile.template_dir, profile.template_files = template_best
        profile.template_ext = ".snbt"
    # 反编译源码树没有模板目录不算异常：第一手在内层 jar（`.nbt`），
    # 由 `probe_template_source` 补齐；两者都无才记未解决。


def _collect_tag_members(subdir: Path) -> set[str]:
    """标签值可能是字符串、`{"id":..,"required":..}`，`#` 前缀是嵌套引用，不算注册表条目。"""
    members: set[str] = set()
    for path in subdir.rglob("*.json"):
        doc = load_json_safe(path)
        if not isinstance(doc, dict):
            continue
        values = doc.get("values")
        if not isinstance(values, list):
            continue
        for item in values:
            ident = item if isinstance(item, str) else None
            if ident is None and isinstance(item, dict):
                ident = item.get("id")
            if not isinstance(ident, str) or ident.startswith("#"):
                continue
            members.add(ident)
    return members


def probe_tag_dirs(data_root: Path, anchors: Anchors, profile: Profile) -> None:
    """给标签目录定注册表归属。

    标签目录可嵌套（`worldgen/biome`）。先在顶层判定，判不出来才下潜：
    `tags/item/<标签名>` 这类子目录是标签名分层，不是注册表分层，
    贸然下潜会把某个标签的成员误当成另一个注册表的条目。
    """
    tags_claim = profile.dirs.get("tags")
    if tags_claim is None:
        return
    ns, _, dir_name = tags_claim.path.partition("/")
    tags_root = data_root / ns / dir_name
    if not tags_root.is_dir():
        return

    for top in sorted(p for p in tags_root.iterdir() if p.is_dir()):
        if _claim_tag_dir(top, tags_root, anchors, profile):
            continue
        for sub in sorted(p for p in top.iterdir() if p.is_dir()):
            _claim_tag_dir(sub, tags_root, anchors, profile)


def _claim_tag_dir(
    sub: Path, tags_root: Path, anchors: Anchors, profile: Profile
) -> bool:
    """给一个标签目录定归属。成功返回 True。

    成功时连同其子目录一并计入：`tags/item/<标签名>/x.json` 是标签名分层，
    成员仍属同一注册表。无法锚定才说明是注册表分层，由调用方逐个下潜。
    """
    files = [f for f in sub.rglob("*.json") if f.is_file()]
    if not files:
        return False
    rel = sub.relative_to(tags_root).as_posix()
    members = _collect_tag_members(sub)
    where = f"{tags_root.parent.name}/{tags_root.name}/{rel}"

    hints = (rel, rel.rsplit("/", 1)[-1])
    found = anchors.best(members, hints)
    if found is None:
        if not members:
            profile.notes.append(
                f"{where} 空标签且无法锚定注册表，条目数 {len(files)}"
            )
            return False
        profile.notes.append(
            f"{where} 成员 {len(members)} 个，无任何锚点覆盖率达标"
        )
        return False

    anchor, coverage = found
    name = anchors.registry_name(anchor)
    profile.tag_dirs[name] = TagDir(
        registry=name,
        path=where,
        files=len(files),
        coverage=coverage,
        status=OK,
    )
    if not members:
        profile.notes.append(f"{where} 为空标签，按目录名锚定到 {name}")
    return True
