"""反编译源码适配器：索引 → idiom → code_link 事实 + 分桶台账。

留痕策略见 `index.py` 的说明：`excluded` 与 `no_anchor` 只记规则名与计数，
`candidate` 里没被任何 idiom 处理的文件**逐文件登记**，带锚点种类与原因。

推断出来的节点名在收尾时对账，见 `verify.py`。
"""

from __future__ import annotations

from pathlib import Path

from ...facts import FactStore, LedgerStatus
from ...probe.profile import Profile
from ..base import Adapter, record
from .common import FAMILY, JAVA_PREFIX
from .idioms.base import Idiom
from .idioms.buckets import exported as bucket_idioms
from .idioms.death_drops import exported as death_drop_idioms
from .idioms.drops import exported as drop_idioms
from .idioms.fluid_buckets import exported as fluid_bucket_idioms
from .idioms.interact import exported as interact_idioms
from .idioms.loot_alias import exported as alias_idioms
from .idioms.place import exported as place_idioms
from .idioms.piglin_barter import exported as piglin_barter_idioms
from .idioms.raid_waves import exported as raid_wave_idioms
from .idioms.sheep import exported as sheep_idioms
from .idioms.structure_containers import exported as structure_container_idioms
from .idioms.structure_entities import exported as structure_entity_idioms
from .idioms.structure_gadgets import exported as gadget_idioms
from .idioms.trades import exported as trade_idioms
from .idioms.transforms import exported as transform_idioms
from .index import ANCHORS, build_index
from .verify import (
    known_structures,
    verify_drop_refs,
    verify_place_refs,
    verify_structure_refs,
    verify_table_refs,
)
from ...paths import pack_java

__all__ = [
    "FAMILY",
    "JAVA_PREFIX",
    "SourceAdapter",
    "default_idioms",
    "known_structures",
    "verify_drop_refs",
    "verify_place_refs",
    "verify_structure_refs",
    "verify_table_refs",
]


def default_idioms() -> list[Idiom]:
    return [
        *sheep_idioms(),
        *trade_idioms(),
        *piglin_barter_idioms(),
        *transform_idioms(),
        *alias_idioms(),
        *place_idioms(),
        *drop_idioms(),
        *bucket_idioms(),
        *fluid_bucket_idioms(),
        *interact_idioms(),
        *raid_wave_idioms(),
        *gadget_idioms(),
        *structure_entity_idioms(),
        *structure_container_idioms(),
        *death_drop_idioms(),
    ]


# 一条说明最多展开几条样例。多出来的按「同类再 N 条」归并。
NOTE_SAMPLES = 8


def _fold_notes(notes: list[str]) -> str:
    """把同一个 idiom 的多条说明折叠成一条。

    台账的语义是「每个输入文件一行」，一个 idiom 的运行时说明不是文件，
    所以只占一行。但内容不能丢：折叠时保留前 `NOTE_SAMPLES` 条原文，
    其余归并成计数，因为「哪些文件没解析出东西」本身是要查的线索。
    """
    if len(notes) <= NOTE_SAMPLES:
        return " ；".join(notes)
    head = " ；".join(notes[:NOTE_SAMPLES])
    return f"{head} ；另有同类说明 {len(notes) - NOTE_SAMPLES} 条"


class SourceAdapter(Adapter):
    id = "src/java"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        java_root = pack_java(pack_dir)
        if not java_root.is_dir():
            store.mark_unavailable(
                FAMILY,
                "输入包内没有反编译源码",
                "输入包的 `java/` 应含 Java 源码；缺它则代码侧机制全部为 UNKNOWN",
            )
            return

        index = build_index(pack_dir, profile.label)
        idioms = default_idioms()

        extracted: dict[str, int] = {}
        handled_files: set[str] = set()

        for idiom in idioms:
            result = idiom.run(index)

            for fact in result.links:
                store.add(fact)
            for path in result.files:
                handled_files.add(path)

            count = len(result.links)
            extracted[idiom.id] = count

            # 一个 idiom 一行说明，键固定。
            #
            # 不能用 `len(store.ledger.rows)` 做键：它随插入位置变化，
            # 合并几条说明就会让旧键全部消失，漂移报告里凭空多出上百条“文件消失”。
            # 实测教训：一次把 365 条 note 聚合成 1 条，vanished 报了 366。
            if result.notes:
                shown = _fold_notes(result.notes)
                record(
                    store,
                    f"{JAVA_PREFIX}/<idiom:{idiom.id}>",
                    FAMILY,
                    status=LedgerStatus.CLASSIFIED_SKIP,
                    rule=f"idiom {idiom.id} 说明",
                    note=shown,
                )
            for path, error in result.failed:
                record(
                    store,
                    f"{JAVA_PREFIX}/{path}",
                    FAMILY,
                    status=LedgerStatus.FAILED,
                    error=error,
                )

            # `min_hits` 是防解析退化的参考下限，不是「本版必须这么大」。
            # 机制随版本搬家（如 26.3 的方块变换迁到数据包，代码侧只剩铜箱 1 条）
            # 会让合法命中数远低于上一版，那不该当缺陷报。
            #
            # 三档处理，区分「不可用」与「只是变了」：
            #   0 条            → unavailable（族级不可用，下游不能用）
            #   >0 但低于下限   → low_yield（事实可用，只是规模变化，留待人工看）
            #   ≥ 下限          → 无动作
            if count == 0:
                store.mark_unavailable(
                    f"idiom:{idiom.id}",
                    "命中 0 条",
                    "该惯用法在本版可能改了实现或整族搬走；"
                    "判据见 docs/shapes.md 与 docs/adr/ 下对应主题",
                )
            elif count < idiom.min_hits:
                store.extra.setdefault("low_yield_idioms", []).append(
                    {
                        "idiom": idiom.id,
                        "hits": count,
                        "reference_floor": idiom.min_hits,
                        "note": "低于参考下限但非零：机制可能部分搬家，已产出的事实仍可用",
                    }
                )

        # 已处理的文件记 parsed
        for path in sorted(handled_files):
            record(
                store,
                f"{JAVA_PREFIX}/{path}",
                FAMILY,
                status=LedgerStatus.PARSED,
                facts=sum(1 for f in store.facts if f.kind == "code_link" and f.prov.file.endswith(path)),
                note="由 idiom 提取",
            )

        # 分桶台账：excluded 与 no_anchor 只记规则名 + 计数
        for rule, count in sorted(index.excluded.items()):
            record(
                store,
                f"{JAVA_PREFIX}/<excluded:{rule}>",
                FAMILY,
                status=LedgerStatus.CLASSIFIED_SKIP,
                rule=f"反编译源码排除规则 {rule}",
                note=f"{count} 个文件",
            )
        record(
            store,
            f"{JAVA_PREFIX}/<no_anchor>",
            FAMILY,
            status=LedgerStatus.CLASSIFIED_SKIP,
            rule="不含任何获取语义锚点",
            note=f"{index.no_anchor} 个文件",
        )

        # 待解释盲区：逐文件登记
        for java in sorted(index.candidates, key=lambda f: f.path):
            if java.path in handled_files:
                continue
            kinds = "、".join(f"{name}（{ANCHORS[name][1]}）" for name in java.anchors)
            record(
                store,
                f"{JAVA_PREFIX}/{java.path}",
                FAMILY,
                status=LedgerStatus.CLASSIFIED_SKIP,
                rule="含获取语义锚点但无 idiom 覆盖",
                note=kinds,
            )

        store.extra["java_index"] = index.as_json(extracted)
        store.extra["java_candidate_unhandled"] = len(index.candidates) - len(handled_files)
        verify_table_refs(store)
        verify_place_refs(store)
        verify_drop_refs(store)
        verify_structure_refs(store)
