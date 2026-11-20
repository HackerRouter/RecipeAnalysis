"""事实库：按内容寻址的存储 + 台账落盘。

事实库键 = 「输入摘要 + 适配器 id + 适配器版本」，输入变了就失效。
事实与台账都写成 JSONL，一行一条，便于 diff 与逐条复核。
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from ..util.jsonio import write_json, write_jsonl
from .schema import Coverage, Fact, Ledger, LedgerRow, LedgerStatus, Prov, Status

# 事实目录里的三个非事实文件。`facts/` 同时是「事实库」的落盘根：事实按种类
# 一文件，台账与汇总并排放在同一层。下游按事实种类取文件，所以要能一眼区分。
LEDGER_FILE = "ledger.jsonl"
SUMMARY_FILE = "summary.json"


def _ledger_row(row: dict) -> LedgerRow:
    """台账行的反向构造。`LedgerRow.as_json` 的键集就是这里的参数集。"""
    return LedgerRow(
        file=row["file"],
        status=LedgerStatus(row["status"]),
        family=row.get("family", "unclassified"),
        rule=row.get("rule"),
        facts=int(row.get("facts", 0)),
        missing=tuple(row.get("missing") or ()),
        error=row.get("error"),
        note=row.get("note"),
    )


@dataclass
class FactStore:
    """一次运行累积的事实与台账。"""

    label: str
    facts: list[Fact] = field(default_factory=list)
    ledger: Ledger = field(default_factory=Ledger)
    # 族级不可用说明（如「该版本无默认组件报告」）。
    # 这不是文件台账：没有文件就没有冒台账行，否则覆盖率统计会被虚高的分母拉偷。
    unavailable: list[dict] = field(default_factory=list)
    # 结构化补充结果（跨来源对账、资源统计等）。不进事实，只进 summary。
    extra: dict = field(default_factory=dict)
    _by_kind: dict[str, list[Fact]] = field(default_factory=lambda: defaultdict(list), repr=False)

    def mark_unavailable(self, family: str, reason: str, note: str = "") -> None:
        row = {"family": family, "reason": reason, "note": note}
        if row not in self.unavailable:
            self.unavailable.append(row)

    @classmethod
    def read(cls, facts_dir: Path, label: str = "") -> "FactStore":
        """从 `output/<label>/facts/` 反序列化，供复盘与 `ra why`。

        为什么不重跑适配器：`run` 已经把事实落盘，重算一次 ingest 要扫七千个
        Java 文件。复盘要的是「输入没变时结论可重算」，而事实就是那层的输入。

        同目录下的 `ledger.jsonl` 与 `summary.json` 不是事实（台账与汇总），
        读事实时按文件名分开处理：台账读回 `store.ledger`，`summary.json`
        里的 `extra` 与 `unavailable`（物品对账、资源统计、族级不可用）也读回来，
        否则复盘看到的覆盖面会缺块。
        """
        store = cls(label=label)
        for path in sorted(facts_dir.glob("*.jsonl")):
            if path.name == LEDGER_FILE:
                for line in path.open(encoding="utf-8"):
                    line = line.strip()
                    if line:
                        store.ledger.add(_ledger_row(json.loads(line)))
                continue
            for line in path.open(encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                store.add(
                    Fact(
                        kind=row["kind"],
                        payload=row["payload"],
                        prov=Prov(**row["prov"]),
                        status=Status(row.get("status", "parsed")),
                        missing=tuple(row.get("missing") or ()),
                        error=row.get("error"),
                        schema=int(row.get("schema", 1)),
                    )
                )
        summary = facts_dir / SUMMARY_FILE
        if summary.is_file():
            doc = json.loads(summary.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                store.unavailable = list(doc.get("unavailable_families") or [])
                store.extra = {
                    key: value
                    for key, value in doc.items()
                    if key
                    not in {
                        "label",
                        "kinds",
                        "status",
                        "ledger",
                        "skipped_rules",
                        "unavailable_families",
                        "coverage",
                    }
                }
        return store

    def add(self, fact: Fact) -> None:
        self.facts.append(fact)
        self._by_kind[fact.kind].append(fact)

    def drop(self, fact: Fact) -> None:
        """剔除一条不合格事实（如节点名推错）。

        只在对账阶段使用，且调用方必须同时落一条台账说明——剔除不等于没发生。
        """
        self.facts.remove(fact)
        rows = self._by_kind.get(fact.kind)
        if rows is not None and fact in rows:
            rows.remove(fact)

    def of_kind(self, kind: str) -> list[Fact]:
        return self._by_kind.get(kind, [])

    def kind_counts(self) -> dict[str, int]:
        return {kind: len(rows) for kind, rows in sorted(self._by_kind.items())}

    def status_counts(self) -> dict[str, int]:
        tally: dict[str, int] = {"parsed": 0, "partial": 0, "failed": 0}
        for fact in self.facts:
            tally[fact.status.value] += 1
        return tally

    def coverage(self) -> list[Coverage]:
        """按族（来源族）统计文件覆盖率。"""
        stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"files": 0, "parsed": 0, "partial": 0, "skipped": 0, "failed": 0}
        )
        for row in self.ledger.rows:
            slot = stats[row.family]
            slot["files"] += 1
            if row.status is LedgerStatus.PARSED:
                slot["parsed"] += 1
            elif row.status is LedgerStatus.PARTIAL:
                slot["partial"] += 1
            elif row.status is LedgerStatus.CLASSIFIED_SKIP:
                slot["skipped"] += 1
            else:
                slot["failed"] += 1
        return [
            Coverage(
                family=family,
                files=slot["files"],
                parsed=slot["parsed"],
                partial=slot["partial"],
                skipped=slot["skipped"],
                failed=slot["failed"],
            )
            for family, slot in sorted(stats.items())
        ]

    def write(self, facts_dir: Path) -> dict[str, Path]:
        """把事实、台账与汇总一起写进事实目录。

        三者同处一层：读 `facts/` 的人要能同时拿到「有哪些记录」「每个输入文件
        的去向」「计数与族级不可用」，分开放会让复盘漏读其中一份。
        """
        paths: dict[str, Path] = {}

        for kind in sorted(self._by_kind):
            path = facts_dir / f"{kind}.jsonl"
            write_jsonl(path, (fact.as_json() for fact in self._by_kind[kind]))
            paths[kind] = path

        ledger_path = facts_dir / LEDGER_FILE
        write_jsonl(ledger_path, (row.as_json() for row in self.ledger.rows))
        paths["ledger"] = ledger_path

        summary_path = facts_dir / SUMMARY_FILE
        write_json(
            summary_path,
            {
                "label": self.label,
                "kinds": self.kind_counts(),
                "status": self.status_counts(),
                "ledger": self.ledger.counts(),
                "skipped_rules": self.ledger.skipped_rules(),
                "unavailable_families": self.unavailable,
                "coverage": [c.as_json() for c in self.coverage()],
                **self.extra,
            },
        )
        paths["summary"] = summary_path
        return paths
