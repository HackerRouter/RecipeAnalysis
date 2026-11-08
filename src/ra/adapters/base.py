"""适配器基类：只做语法还原。

适配器的义务有三条：
1. 遇到不认识的字段必须报错或标 `partial`，不得忽略
2. 不写语义（`serializer → station` 属 IR 层）
3. 每条事实带 provenance，并给台账留一行
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from ..facts import Fact, FactStore, LedgerRow, LedgerStatus
from ..probe.profile import Profile

ADAPTER_SCHEMA_VERSION = 1


class Adapter(ABC):
    """一个来源族一个适配器。"""

    id: str = ""
    version: int = ADAPTER_SCHEMA_VERSION

    @abstractmethod
    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        """产出事实并登记台账。"""


def record(
    store: FactStore,
    file: str,
    family: str,
    *,
    facts: int = 0,
    status: LedgerStatus | None = None,
    missing: tuple[str, ...] = (),
    rule: str | None = None,
    error: str | None = None,
    note: str | None = None,
) -> None:
    """登记一行的台账。

    台账与事实同源：产出事实就记 `parsed`；缺项但仍有产出记 `partial` 并把
    `missing` 原样写上；没产出就要说清是「整棵排除」还是「失败」。
    """
    if status is None:
        status = LedgerStatus.PARTIAL if missing else LedgerStatus.PARSED
    store.ledger.add(
        LedgerRow(
            file=file,
            status=status,
            family=family,
            rule=rule,
            facts=facts,
            missing=tuple(missing),
            error=error,
            note=note,
        )
    )


def iter_json_files(root: Path) -> Iterator[Path]:
    yield from sorted(p for p in root.rglob("*.json") if p.is_file())


def rel_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()
