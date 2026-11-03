"""适配器编排：按 Profile 决定跑哪些适配器。

顺序即依赖：注册表先（其他族要它当全集），数据包各族互相独立，最后是覆盖全树的
台账对账——每个输入文件都要有交代，出现新目录/新扩展名且无规则即硬失败。
"""

from __future__ import annotations

from pathlib import Path

from ..errors import AdapterError
from ..facts import FactStore, LedgerStatus
from ..probe.profile import Profile
from .base import Adapter, record
from .block_transform import BlockTransformerAdapter
from .components import ComponentsAdapter
from .loot import LootAdapter
from .probe_facts import ProfileAdapter
from .recipes import RecipeAdapter
from .registries import RegistryAdapter
from .source import SourceAdapter
from .spawners import SpawnerConfigAdapter
from .tags import TagAdapter
from .templates import TemplateAdapter
from .trades import TradeAdapter
from .worldgen import WorldgenAdapter
from ..paths import pack_assets, pack_data

# 已知且会被解析或明确排除的扩展名。其余扩展名出现即硬失败。
KNOWN_SUFFIXES = frozenset({".json", ".snbt", ".png", ".mcmeta", ".txt", ".lang", ".json5"})


def default_adapters() -> list[Adapter]:
    return [
        ProfileAdapter(),
        RegistryAdapter(),
        ComponentsAdapter(),
        TagAdapter(),
        RecipeAdapter(),
        LootAdapter(),
        TemplateAdapter(),
        WorldgenAdapter(),
        SpawnerConfigAdapter(),
        BlockTransformerAdapter(),
        TradeAdapter(),
        SourceAdapter(),
    ]


def run_adapters(
    profile: Profile,
    pack_dir: Path,
    store: FactStore,
    adapters: list[Adapter] | None = None,
) -> None:
    for adapter in adapters if adapters is not None else default_adapters():
        adapter.run(profile, pack_dir, store)


def audit_tree(profile: Profile, pack_dir: Path, store: FactStore) -> list[str]:
    """核对每个输入文件都有交代。

    审计范围是 `src/main/resources/` 下的 `data/` 与 `assets/`：
    前者是获取路径的输入，后者是资源（含物品全集的第二条途径）。
    反编译源码不在本阶段范围，属 code_link 族。

    返回未登记的文件（首若干条），空列表表示全覆盖。
    实验包整棵排除要带规则名，不能默默不算。
    """
    registered = {row.file for row in store.ledger.rows}
    resources_root = pack_dir
    data_root = resources_root / "data"

    unaccounted: list[str] = []
    unknown_suffix: list[str] = []

    roots = [d for d in (data_root, resources_root / "assets") if d.is_dir()]
    if not roots:
        return unaccounted

    excluded_prefixes = tuple(f"data/{d}/" for d in profile.excluded_dirs)

    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = path.relative_to(pack_dir).as_posix()
            if rel.startswith(excluded_prefixes):
                continue
            if path.name in BUILD_MARKERS:
                continue
            # 先看有没有交代过，再看扩展名：已登记的文件不管扩展名都算有交代
            if rel in registered:
                continue
            if path.suffix not in KNOWN_SUFFIXES:
                unknown_suffix.append(rel)
                continue
            unaccounted.append(rel)

    for rel in unknown_suffix[:20]:
        record(
            store,
            rel,
            "audit",
            status=LedgerStatus.FAILED,
            error=f"未知扩展名 {Path(rel).suffix}，无处理规则",
        )
    for rel in unaccounted[:20]:
        record(
            store,
            rel,
            "audit",
            status=LedgerStatus.FAILED,
            error="没有适配器认领该文件",
        )

    return unknown_suffix + unaccounted


def skip_excluded_dirs(profile: Profile, pack_dir: Path, store: FactStore) -> None:
    """实验包整棵排除，逐目录登记规则名。"""
    data_root = pack_data(pack_dir)
    for rel in profile.excluded_dirs:
        target = data_root / rel
        count = sum(1 for _ in target.rglob("*") if _.is_file()) if target.is_dir() else 0
        record(
            store,
            f"data/{rel}",
            "pack_datapack",
            status=LedgerStatus.CLASSIFIED_SKIP,
            rule="实验包整棵排除",
            note=f"{count} 个文件，属 datapacks/ 下的非原版内容",
        )


# 由适配器负责的注册表族。其余数据包目录一律登记为不参与推理，不静默丢弃。
ANALYZED_FAMILIES = frozenset(
    {
        "recipe",
        "loot_table",
        "tags",
        "worldgen",
        "villager_trade",
        "trade_set",
        "block_transformer",
    }
)

# 构建标记文件：空文件、无扩展名，不是数据。
BUILD_MARKERS = frozenset({".mcassetsroot", ".gitkeep", "pack.mcmeta"})


# 由专用适配器读的数据包顶级目录。它们不在 `probe.dirs` 里
# （那些是成就表规模的注册表），也不是 inert——但必须是「一个目录一个负责者」。
# 不列在这里，`skip_inert_registries` 会先把它逐文件登记成「不参与推理」，
# 适配器再登记就撞台账（实测：`台账重复登记同一文件`）。
ADAPTER_DIRS = frozenset({"trial_spawner"})


def skip_inert_registries(profile: Profile, pack_dir: Path, store: FactStore) -> None:
    """把不参与获取路径推理的注册表目录逐**文件**登记。

    这不是「白名单」：判据是「没有适配器负责这一族」，不是逐条列出注册名。
    方案要求每个输入文件都有一行交代，因此不按目录汇总。
    """
    data_root = pack_data(pack_dir)
    covered = {claim.path for claim in profile.dirs.values()}
    covered |= {tag.path for tag in profile.tag_dirs.values()}
    if profile.template_dir:
        covered.add(profile.template_dir)
    covered |= {f"{key.split('/')[0]}/worldgen" for key in profile.worldgen_counts}

    for ns_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        for top in sorted(p for p in ns_dir.iterdir() if p.is_dir()):
            rel = f"{ns_dir.name}/{top.name}"
            if rel in covered or top.name == "datapacks" or top.name in ADAPTER_DIRS:
                continue
            for path in sorted(p for p in top.rglob("*") if p.is_file()):
                record(
                    store,
                    path.relative_to(pack_dir).as_posix(),
                    "inert_registry",
                    status=LedgerStatus.CLASSIFIED_SKIP,
                    rule="该注册表不参与获取路径推理",
                    note=f"目录 {rel}",
                )

    for marker in BUILD_MARKERS:
        path = data_root / marker
        if path.exists():
            record(
                store,
                f"data/{marker}",
                "build_marker",
                status=LedgerStatus.CLASSIFIED_SKIP,
                rule="构建标记文件",
                note="空标记，不含数据",
            )


def require_complete(unaccounted: list[str]) -> None:
    if unaccounted:
        preview = "\n  ".join(unaccounted[:20])
        raise AdapterError(
            f"有 {len(unaccounted)} 个输入文件没有交代（前 20）：\n  {preview}"
        )


# 资源目录：模型、贴图、语言文件、方块状态等。
# 它们不是获取路径的输入，但属于输入包内容，必须逐文件交代。
ASSET_FAMILIES = ("models", "blockstates", "textures", "lang", "font", "atlases", "sounds", "particles")


def sweep_assets(pack_dir: Path, store: FactStore) -> dict[str, int]:
    """逐文件登记 `assets/` 下的资源。

    这些不是获取路径的输入，但属输入包内容，必须逐文件交代（红线 3）。
    服务端 jar 里只有 `lang`，用户通常不会提供 `assets/`；给了就要登记。
    """
    assets_root = pack_assets(pack_dir)
    counts: dict[str, int] = {}
    if not assets_root.is_dir():
        return counts

    for ns_dir in sorted(p for p in assets_root.iterdir() if p.is_dir()):
        # 命名空间根下也可能有散文件（如 `gpu_warnlist.json`），它们不属于任何资源族
        loose = sorted(f for f in ns_dir.iterdir() if f.is_file())
        if loose:
            counts[f"{ns_dir.name}/<root>"] = len(loose)
            for path in loose:
                record(
                    store,
                    path.relative_to(pack_dir).as_posix(),
                    "asset",
                    status=LedgerStatus.CLASSIFIED_SKIP,
                    rule="资源文件，不参与获取路径推理",
                    note=f"assets/{ns_dir.name} 根下散文件",
                )

        for family in sorted(p for p in ns_dir.iterdir() if p.is_dir()):
            files = sorted(f for f in family.rglob("*") if f.is_file())
            if not files:
                continue
            counts[f"{ns_dir.name}/{family.name}"] = len(files)
            rule = (
                "物品全集的第二条途径"
                if family.name == "items"
                else "资源文件，不参与获取路径推理"
            )
            for path in files:
                record(
                    store,
                    path.relative_to(pack_dir).as_posix(),
                    "asset",
                    status=LedgerStatus.CLASSIFIED_SKIP,
                    rule=rule,
                    note=f"assets/{ns_dir.name}/{family.name}",
                )
    return counts
