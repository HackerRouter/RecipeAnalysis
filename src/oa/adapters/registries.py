"""注册表适配器：物品全集、方块全集，以及各注册表的条目清单。

注册名一律从输入读，不在仓库留副本。与反编译源码的 `assets/minecraft/items` 做交叉校验
属桥接层，这里只如实记录运行期导出的条目。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, record

REGISTRIES_FILE = "registries.json"
FAMILY = "registry"


class RegistryAdapter(Adapter):
    id = "jar/registries"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        if profile.reports_root is None:
            return
        path = Path(profile.reports_root) / REGISTRIES_FILE
        file_label = f"reports/{REGISTRIES_FILE}"
        if not path.is_file():
            record(
                store,
                file_label,
                FAMILY,
                status=LedgerStatus.FAILED,
                error="registries.json 不存在，无法取得注册表全集",
            )
            return

        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return

        produced = 0
        for name, body in doc.items():
            if not isinstance(body, dict) or not isinstance(body.get("entries"), dict):
                record(
                    store,
                    f"{file_label}#{name}",
                    FAMILY,
                    status=LedgerStatus.FAILED,
                    error=f"注册表 {name} 结构异常，缺 entries 对象",
                )
                continue
            entries = body["entries"]
            store.add(
                Fact(
                    kind="registry",
                    payload={
                        "registry": name,
                        "entries": sorted(entries),
                        "count": len(entries),
                        "default": body.get("default"),
                        "protocol_id": body.get("protocol_id"),
                    },
                    prov=Prov(input="jar", file=file_label, ptr=name),
                )
            )
            produced += 1

        record(
            store,
            file_label,
            FAMILY,
            facts=produced,
            note=f"{produced} 个注册表",
        )
