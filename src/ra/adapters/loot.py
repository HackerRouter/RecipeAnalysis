"""数据包适配器：战利品表。

**语法归一见共用模块 `ra.mcshared.loot`**（物理只有一份，junction 拼进来）。
本文件只保留适配器的三项义务：逐文件产生的台账、事实的状态与 provenance。
方言判定、条件/函数归一、条目树摊平都在共用模块里。

下面再导出 `condition_type` / `normalize_conditions` / `normalize_functions` /
`walk_entry`，是为了让调用方不必知道共用模块的路径——它们就是共用模块的函数本身。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..mcshared.loot import (
    ENTRY_KINDS,
    IDENTITY_KEYS,
    condition_type,
    fact_payload,
    normalize_conditions,
    normalize_functions,
    normalize_table,
    table_id_from_file,
    walk_entry,
)
from .base import Adapter, data_root, iter_json_files, record, rel_posix
from ..probe.profile import Profile
from ..util.jsonio import read_json

FAMILY = "loot_table"

__all__ = [
    "ENTRY_KINDS",
    "IDENTITY_KEYS",
    "LootAdapter",
    "condition_type",
    "normalize_conditions",
    "normalize_functions",
    "walk_entry",
]


class LootAdapter(Adapter):
    id = "src/loot"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        claim = profile.dirs.get("loot_table")
        if claim is None:
            record(
                store,
                "data/*/loot_table",
                FAMILY,
                status=LedgerStatus.FAILED,
                error="未定位战利品表目录",
            )
            return
        ns, _, rel = claim.path.partition("/")
        data = data_root(profile, pack_dir)
        root = data / ns / rel
        for path in iter_json_files(root):
            self._one(path, data.parent, root, store)

    def _one(self, path: Path, pack_dir: Path, root: Path, store: FactStore) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return

        table = normalize_table(doc, table_id_from_file(file_label))
        missing = list(table.missing)
        store.add(
            Fact(
                kind="loot_table",
                payload=fact_payload(table),
                prov=Prov(input="src", file=file_label),
                status=Status.PARTIAL if missing else Status.PARSED,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, missing=tuple(missing))
