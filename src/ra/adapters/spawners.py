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
from .base import Adapter, data_root, iter_json_files, record, rel_posix

FAMILY = "spawner_config"
DIRNAME = "trial_spawner"


class SpawnerConfigAdapter(Adapter):
    id = "src/spawner_config"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        data = data_root(profile, pack_dir)
        found = 0
        for namespace_dir in sorted(p for p in data.iterdir() if p.is_dir()):
            root = namespace_dir / DIRNAME
            if not root.is_dir():
                continue
            for path in iter_json_files(root):
                self._one(path, data.parent, namespace_dir.name, root, store)
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
            row = {
                "id": ident,
                "weight": entry.get("weight") if isinstance(entry.get("weight"), int) else None,
            }
            equipment = data.get("equipment") if isinstance(data, dict) else None
            if isinstance(equipment, dict) and isinstance(equipment.get("loot_table"), str):
                row["equipment"] = equipment["loot_table"]
            entities.append(row)

        # 不祥配置独有的「打完弹什么」：表 + 权重。不祥钥匙就在这里，
        # 它是不祥宝库能开的唯一前提，丢掉这张表就等于丢掉整条链。
        eject: list[dict] = []
        for index, entry in enumerate(doc.get("loot_tables_to_eject") or []):
            if not isinstance(entry, dict):
                missing.append(f"loot_tables_to_eject[{index}] 不是对象")
                continue
            table = entry.get("data")
            if not isinstance(table, str):
                missing.append(f"loot_tables_to_eject[{index}].data 缺失")
                continue
            eject.append(
                {
                    "table": table,
                    "weight": entry.get("weight") if isinstance(entry.get("weight"), int) else None,
                }
            )

        # 难度参数照原值保留：下游要按波次/同时存在数建模难度，折算会丢原值。
        difficulty: dict[str, object] = {}
        for key in (
            "simultaneous_mobs",
            "simultaneous_mobs_added_per_player",
            "total_mobs",
            "total_mobs_added_per_player",
            "ticks_between_spawn",
        ):
            value = doc.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                difficulty[key] = value

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

        payload = {
            "id": ident,
            "namespace": namespace,
            "tier": tier,
            "entities": entities,
        }
        if eject:
            payload["eject_tables"] = eject
        if difficulty:
            payload["difficulty"] = difficulty

        store.add(
            Fact(
                kind="spawner_config",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=Status.PARTIAL if missing else Status.PARSED,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, note="；".join(missing) or None)
