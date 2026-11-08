"""数据包适配器：配方。

配方 JSON 的方言差异、原料槽通则与产出归一在 `ra.mcshared.recipes`；
本文件只负责逐文件台账与事实的 `prov` / `status`。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..mcshared.recipes import parse_ingredient, parse_result
from ..mcshared.recipes import normalize_recipe
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "recipe"

__all__ = ["RecipeAdapter", "parse_ingredient", "parse_result"]


class RecipeAdapter(Adapter):
    id = "src/recipes"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        claim = profile.dirs.get("recipe")
        if claim is None:
            record(
                store,
                "data/*/recipe",
                FAMILY,
                status=LedgerStatus.FAILED,
                error="未定位配方目录",
            )
            return
        ns, _, rel = claim.path.partition("/")
        root = pack_data(pack_dir) / ns / rel
        for path in iter_json_files(root):
            self._one(path, pack_dir, store)

    def _one(self, path: Path, pack_dir: Path, store: FactStore) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return

        serializer = doc.get("type")
        if not isinstance(serializer, str):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="缺少 type")
            return

        payload, missing = normalize_recipe(doc)

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="recipe",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, missing=tuple(missing))
