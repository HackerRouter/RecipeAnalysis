"""注册表锚点：判定目录与标签归属的依据。

锚点有两类，缺一不可：

1. **运行期导出** `registries.json`——只 dump `BuiltInRegistries`，含 item / block /
   entity_type / potion 等。
2. **数据包自身目录**——`data/<ns>/<path>/<id>.json` 的文件相对路径就是该注册表的
   条目 ID。数据包驱动的注册表（`enchantment`、`trim_pattern`、`worldgen/biome`、
   `villager_trade`）不在 `registries.json` 里，只能靠这一类。

第二类不是在猜：注册表条目 ID 与文件路径是同一套命名，是数据包格式本身的约定。
判断的是「这堆成员像不像那个目录的条目」，覆盖率低于阈值就不采用。
"""

from __future__ import annotations

from pathlib import Path

from .registries import Registries

# 目录归属判定的最低覆盖率。低于此值不采用该锚点，记 UNKNOWN。
COVERAGE_MIN = 0.9

# 单个目录视为「注册表目录」的最少文件数。低于此值可能只是杂项目录。
MIN_DIR_FILES = 2


def datapack_entries(data_root: Path, namespace: str, skip: tuple[str, ...]) -> dict[str, set[str]]:
    """把 `data/<ns>/` 下每个目录编译成「注册表名 → 条目 ID 集合」。

    注册表名是该目录相对 `data/<ns>/` 的路径（`enchantment`、`worldgen/biome`）。
    条目 ID 是文档相对**该注册表根**的路径去掉 `.json`——注册表 ID 不含目录名，
    `data/minecraft/worldgen/biome/badlands.json` 的条目 ID 是 `badlands`。
    """
    ns_dir = data_root / namespace
    if not ns_dir.is_dir():
        return {}

    entries: dict[str, set[str]] = {}
    for top in sorted(p for p in ns_dir.iterdir() if p.is_dir()):
        if top.name in skip:
            continue
        flat = _collect(top)
        if len(flat) >= MIN_DIR_FILES:
            entries[top.name] = flat
        for sub in sorted(p for p in top.iterdir() if p.is_dir()):
            nested = _collect(sub)
            if len(nested) >= MIN_DIR_FILES:
                entries[f"{top.name}/{sub.name}"] = nested
    return entries


def _collect(directory: Path) -> set[str]:
    """条目 ID = 相对该目录的 JSON 路径，去扩展名。"""
    return {path.relative_to(directory).with_suffix("").as_posix() for path in directory.rglob("*.json")}


def _normalize(ident: str) -> str:
    return ident.split(":", 1)[1] if ":" in ident else ident


class Anchors:
    """两类锚点的合并视图。"""

    def __init__(self, registries: Registries, datapack: dict[str, set[str]]) -> None:
        self._registries = registries
        self._datapack = datapack

    def candidates(self) -> list[str]:
        """全部可用锚点名。运行期在前（更权威），数据包目录补其后。"""
        names = [f"registry:{n}" for n in self._registries.names()]
        names += [f"datapack:{n}" for n in sorted(self._datapack)]
        return names

    def entries(self, anchor: str) -> set[str]:
        kind, _, name = anchor.partition(":")
        if kind == "registry":
            return {_normalize(e) for e in self._registries.entries(name)}
        return set(self._datapack.get(name, ()))

    def score(self, members: set[str], anchor: str) -> float:
        pool = self.entries(anchor)
        if not pool or not members:
            return 0.0
        normalized = {_normalize(m) for m in members}
        return len(normalized & pool) / len(normalized)

    def best(self, members: set[str], hints: tuple[str, ...] = ()) -> tuple[str, float] | None:
        """给一批成员找最匹配的锚点。

        `hints` 是行为者自己给出的名字线索（例如标签子目录名），
        优先在同名锚点里找，命中即用——这是最强的信号，不必再看覆盖率排序。

        成员为空（空标签）时只能靠名字：同名锚点存在即归属，置信记为 1.0；
        否则返回 None。空标签仍是一条合法事实，不能因无成员就丢掉。
        """
        for hint in hints:
            for kind in ("datapack", "registry"):
                anchor = f"{kind}:{hint}"
                if not members:
                    if self._exists(anchor):
                        return anchor, 1.0
                    continue
                ratio = self.score(members, anchor)
                if ratio >= COVERAGE_MIN:
                    return anchor, ratio

        if not members:
            return None

        best: tuple[str, float] | None = None
        for anchor in self.candidates():
            ratio = self.score(members, anchor)
            if ratio < COVERAGE_MIN:
                continue
            if best is None or ratio > best[1]:
                best = (anchor, ratio)
        return best

    def _exists(self, anchor: str) -> bool:
        kind, _, name = anchor.partition(":")
        if kind == "registry":
            return name in self._registries.by_name
        return name in self._datapack

    def registry_name(self, anchor: str) -> str:
        """锚点 → 注册表名，形如 `minecraft:<name>`。

        `registries.json` 的锚点名本身已带命名空间（`minecraft:item`），
        数据包目录的锚点名是相对路径（`worldgen/biome`），两者都要归一。
        """
        _, _, name = anchor.partition(":")
        return name if ":" in name else f"minecraft:{name}"
