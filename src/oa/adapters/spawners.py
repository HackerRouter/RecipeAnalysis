"""数据包适配器：试炼刷怪笼配置。

`data/<ns>/trial_spawner/**/*.json` 是「这个刷怪笼会刷什么」的**唯一**数据包来源。

```json
{
  "simultaneous_mobs": 1.0,
  "spawn_potentials": [
    { "data": { "entity": { "id": "minecraft:breeze" } }, "weight": 1 }
  ],
  "ticks_between_spawn": 20,
  "total_mobs": 2.0
}
```

## 为什么必须单列一族

结构 JSON 的 `spawn_overrides` 只覆盖「结构整体刷什么」，`trial_chambers` 的那个
字段是**空数组**——试炼密室的怪物全部来自刷怪笼，走的是这份注册表。
不读它，`breeze` 就不存在于任何事实里，`breeze_rod` 与 `mace` 因此不可达。

## 事实形状

```json
{
  "id": "trial_chamber/breeze/normal",
  "namespace": "minecraft",
  "tier": "normal",
  "entities": [{"id": "minecraft:breeze", "weight": 1}]
}
```

只取实体 id 与权重。数量、间隔、同时存在上限都是**难度**参数，
不影响「会不会刷」这个判断（存在性语义）。

`tier` 取文件名（`normal` / `ominous`），两者都能通过不同途径触发，
对可达性无差别，放 `meta` 供报告展示。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "spawner_config"
DIRNAME = "trial_spawner"


class SpawnerConfigAdapter(Adapter):
    id = "src/spawner_config"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        data_root = pack_data(pack_dir)
        found = 0
        for namespace_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
            root = namespace_dir / DIRNAME
            if not root.is_dir():
                continue
            for path in iter_json_files(root):
                self._one(path, pack_dir, namespace_dir.name, root, store)
                found += 1

        if found == 0:
            # 1.18.2 没有试炼密室，这是**正确**的空；但不是「实现缺失」，
            # 所以给族级登记而不是错误
            store.mark_unavailable(
                FAMILY,
                "该版本数据包内无 trial_spawner 目录",
                "试炼刷怪笼是 1.21 引入的；没有该目录的版本本来就没有这类实体来源",
            )

    def _one(
        self, path: Path, pack_dir: Path, namespace: str, root: Path, store: FactStore
    ) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return
        if not isinstance(doc, dict):
            record(
                store,
                file_label,
                FAMILY,
                status=LedgerStatus.FAILED,
                error="试炼刷怪笼配置应为对象",
            )
            return

        entities: list[dict] = []
        missing: list[str] = []
        for index, entry in enumerate(doc.get("spawn_potentials") or []):
            if not isinstance(entry, dict):
                missing.append(f"spawn_potentials[{index}] 不是对象")
                continue
            data = entry.get("data")
            entity = data.get("entity") if isinstance(data, dict) else None
            ident = entity.get("id") if isinstance(entity, dict) else None
            if not isinstance(ident, str):
                missing.append(f"spawn_potentials[{index}].data.entity.id 缺失")
                continue
            entities.append(
                {
                    "id": ident,
                    "weight": entry.get("weight") if isinstance(entry.get("weight"), int) else None,
                }
            )

        # 相对目录名就是配置 id：`trial_chamber/breeze/normal`
        local = rel_posix(path, root)
        ident = local[: -len(".json")] if local.endswith(".json") else local
        tier = ident.rsplit("/", 1)[-1] if "/" in ident else ""

        if not entities:
            record(
                store,
                file_label,
                FAMILY,
                status=LedgerStatus.FAILED,
                error="配置里没有可解析的 spawn_potentials；" + "；".join(missing),
            )
            return

        store.add(
            Fact(
                kind="spawner_config",
                payload={
                    "id": ident,
                    "namespace": namespace,
                    "tier": tier,
                    "entities": entities,
                },
                prov=Prov(input="src", file=file_label),
                status=Status.PARTIAL if missing else Status.PARSED,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, note="；".join(missing) or None)
