"""注册表索引：物品全集、默认组件的取值域都从这里来。

注册名一律运行时读，不在代码或文档留副本。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import ProbeError
from ..util.jsonio import read_json


@dataclass(frozen=True)
class Registries:
    by_name: dict[str, dict]

    @classmethod
    def load(cls, path: Path) -> "Registries":
        raw = read_json(path)
        if not isinstance(raw, dict) or not raw:
            raise ProbeError(f"registries.json 为空或格式不对：{path}")
        for name, body in raw.items():
            if not isinstance(body, dict) or "entries" not in body:
                raise ProbeError(f"注册表结构异常：{name} 缺 entries")
        return cls(raw)

    def names(self) -> list[str]:
        return sorted(self.by_name)

    def count(self, name: str) -> int:
        return len(self.by_name.get(name, {}).get("entries", {}))

    def entries(self, name: str) -> set[str]:
        return set(self.by_name.get(name, {}).get("entries", {}))

    def counts(self, prefixes: tuple[str, ...] | None = None) -> dict[str, int]:
        names = self.names()
        if prefixes:
            names = [n for n in names if n.startswith(prefixes)]
        return {n: self.count(n) for n in names}

    def resolve_members(
        self, members: set[str], candidates: list[str], min_coverage: float = 0.9
    ) -> list[tuple[str, float]]:
        """给定一批成员 ID，返回每个注册表的命中率，按命中率降序。"""
        if not members:
            return []
        scored: list[tuple[str, float]] = []
        for name in candidates:
            pool = self.entries(name)
            if not pool:
                continue
            hit = len(members & pool) / len(members)
            if hit >= min_coverage:
                scored.append((name, hit))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored
