"""事实记录与文件台账。

事实只做语法还原，不写语义：`serializer` 原样保留，`serializer → station`
属于 IR 的知识映射，不在这一层。

三个 status：
- `parsed`：结构完整，字段按该方言全部取出
- `partial`：能取到一部分，`missing` 说明缺什么
- `failed`：解析失败，`error` 记原因

台账用同一组三态（`LedgerStatus`），并额外允许 `classified_skip`：
文件整棵不参与推理时记它，必须带规则名。

没有 provenance 的事实不允许入 IR，因此在构造时就强制带 `prov`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA_VERSION = 1

# 事实种类。新增种类属契约变更，走 ADR（见 docs/adr/）。
KINDS = (
    "registry",
    "components",
    "tag",
    "recipe",
    "loot_table",
    "trade",
    "worldgen",
    "spawner_config",
    "template",
    "structure_container",
    "block_transform",
    "code_link",
    "pack_delta",
    "profile",
)


class Status(str, Enum):
    PARSED = "parsed"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class Prov:
    """provenance。缺任一项不可复算。"""

    input: str  # src / jar / pack
    file: str
    ptr: str = ""

    def as_json(self) -> dict:
        return {"input": self.input, "file": self.file, "ptr": self.ptr}


@dataclass(frozen=True)
class Fact:
    kind: str
    payload: dict[str, Any]
    prov: Prov
    status: Status = Status.PARSED
    missing: tuple[str, ...] = ()
    error: str | None = None
    schema: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"未知事实种类 {self.kind!r}，允许：{', '.join(KINDS)}")
        if self.status is Status.PARTIAL and not self.missing:
            raise ValueError("partial 事实必须说明 missing")
        if self.status is Status.FAILED and not self.error:
            raise ValueError("failed 事实必须带 error")

    def as_json(self) -> dict:
        out: dict[str, Any] = {
            "kind": self.kind,
            "schema": self.schema,
            "status": self.status.value,
            "payload": self.payload,
            "prov": self.prov.as_json(),
        }
        if self.missing:
            out["missing"] = list(self.missing)
        if self.error:
            out["error"] = self.error
        return out


class LedgerStatus(str, Enum):
    PARSED = "parsed"
    PARTIAL = "partial"
    CLASSIFIED_SKIP = "classified_skip"
    FAILED = "failed"


@dataclass
class LedgerRow:
    """每个输入文件给一行交代。`classified_skip` 必须给出规则名。"""

    file: str
    status: LedgerStatus
    family: str = "unclassified"
    rule: str | None = None
    facts: int = 0
    missing: tuple[str, ...] = ()
    error: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.status is LedgerStatus.CLASSIFIED_SKIP and not self.rule:
            raise ValueError(f"classified_skip 必须给规则名：{self.file}")
        if self.status is LedgerStatus.PARTIAL and not self.missing:
            raise ValueError(f"partial 必须给 missing：{self.file}")
        if self.status is LedgerStatus.FAILED and not self.error:
            raise ValueError(f"failed 必须给 error：{self.file}")

    def as_json(self) -> dict:
        out: dict[str, Any] = {
            "file": self.file,
            "status": self.status.value,
            "family": self.family,
            "facts": self.facts,
        }
        if self.rule:
            out["rule"] = self.rule
        if self.missing:
            out["missing"] = list(self.missing)
        if self.error:
            out["error"] = self.error
        if self.note:
            out["note"] = self.note
        return out


@dataclass
class Ledger:
    """文件台账。同一路径跨运行的状态变化要报。"""

    rows: list[LedgerRow] = field(default_factory=list)
    _seen: dict[str, LedgerStatus] = field(default_factory=dict, repr=False)

    def add(self, row: LedgerRow) -> None:
        if row.file in self._seen:
            raise ValueError(f"台账重复登记同一文件：{row.file}")
        self._seen[row.file] = row.status
        self.rows.append(row)

    def counts(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for row in self.rows:
            tally[row.status.value] = tally.get(row.status.value, 0) + 1
        return tally

    def failed(self) -> list[LedgerRow]:
        return [r for r in self.rows if r.status is LedgerStatus.FAILED]

    def skipped_rules(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for row in self.rows:
            if row.status is LedgerStatus.CLASSIFIED_SKIP and row.rule:
                tally[row.rule] = tally.get(row.rule, 0) + 1
        return tally

    def diff_against(self, previous: dict[str, str]) -> list[dict]:
        """与上一次台账比较，报出状态变化的文件。"""
        changes: list[dict] = []
        for row in self.rows:
            before = previous.get(row.file)
            if before is not None and before != row.status.value:
                changes.append({"file": row.file, "before": before, "after": row.status.value})
        return changes


@dataclass(frozen=True)
class Coverage:
    """每族的文件覆盖率。下降超阈值即报警。"""

    family: str
    files: int
    parsed: int
    skipped: int
    failed: int
    partial: int = 0

    @property
    def ratio(self) -> float:
        """有产出的文件比例。`partial` 有产出，只是字段不全。"""
        return (self.parsed + self.partial) / self.files if self.files else 0.0

    def as_json(self) -> dict:
        return {
            "family": self.family,
            "files": self.files,
            "parsed": self.parsed,
            "partial": self.partial,
            "skipped": self.skipped,
            "failed": self.failed,
            "ratio": round(self.ratio, 4),
        }
