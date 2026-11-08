"""数据包适配器：结构模板（SNBT）。

模板的第一手在服务端 jar 内层（`.nbt`），由 `inputs/structures.py` 用
`net.minecraft.data.Main --dev` 转成 `.snbt`；反编译源码树的同名副本 palette 被抹空，
只作为退回路径。无论哪种来源，适配器读到的都是**文本** SNBT，不需要 NBT 解析器。

SNBT 读取与 payload 归一见 `ra.mcshared.snbt`；本文件只负责来源选择、
族级不可用登记与逐文件台账。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..mcshared.snbt import SnbtError, normalize_template, parse_snbt, template_id_from_file
from ..probe.profile import Profile
from .base import Adapter, record, rel_posix
from ..paths import pack_data

FAMILY = "template"

__all__ = ["SnbtError", "TemplateAdapter", "parse_snbt"]


class TemplateAdapter(Adapter):
    id = "src/templates"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        """读模板。第一手是 jar 内层模板经 `--dev` 转出的 SNBT。

        反编译源码树的 `.snbt` 是打包副本，26.3 的 palette 被抹成空串；该来源只在 jar 侧
        不可用时才退回，并在 profile 里留痕（见 `_probe_template_source`）。
        """
        if profile.template_source == "jar" and profile.template_root and profile.template_dir:
            data_root = Path(profile.template_root) / "data"
            input_kind = "jar"
            label_base = None  # 相对 data_root 的父目录记账
        elif profile.template_dir:
            data_root = pack_data(pack_dir)
            input_kind = "src"
            label_base = pack_dir
        else:
            record(
                store,
                "data/*/structure",
                FAMILY,
                status=LedgerStatus.FAILED,
                error="结构模板不可得（jar 内层与反编译源码树都没有）",
            )
            return

        ns, _, rel = profile.template_dir.partition("/")
        root = data_root / ns / rel
        base = label_base if label_base is not None else data_root.parent
        paths = sorted(p for p in root.rglob("*.snbt") if p.is_file())
        if not paths:
            record(
                store,
                f"{ns}/{rel}",
                FAMILY,
                status=LedgerStatus.FAILED,
                error=f"模板目录里没有 .snbt：{root}",
            )
            return
        for path in paths:
            self._one(path, base, store, input_kind)

        if input_kind == "jar":
            self._skip_source_copies(profile, pack_dir, store)

        # 汇总「普通方块身份不可读」的比例，做族级登记。
        #
        # 单个模板的 blocks 为空不能直接判异常（拼图空壳层本来就全空气），
        # 但整族全空说明来源缺了方块身份——这两种必须分清，
        # 否则下游会把「我看不到方块」读成「结构里没有方块」。
        facts = store.of_kind("template")
        if facts:
            unreadable = sum(1 for f in facts if f.payload.get("blocks_unreadable"))
            if unreadable:
                with_entities = sum(
                    1 for f in facts if f.payload.get("block_entity_ids")
                )
                store.mark_unavailable(
                    "template.blocks",
                    f"{unreadable}/{len(facts)} 个模板的普通方块身份不可读",
                    f"当前模板来源（{profile.template_source}）的 palette 全为空串，"
                    f"只有方块实体的 nbt.id 保留；其中 {with_entities} 个模板能从 nbt.id 取到"
                    "方块实体身份。普通方块（如 stone、purpur_block）的『在哪个结构里出现』不可得",
                )

    def _skip_source_copies(
        self, profile: Profile, pack_dir: Path, store: FactStore
    ) -> None:
        """jar 来源生效时，反编译源码树的同名模板逐文件登记为不参与推理。

        不静默忽略：这 1511 个文件仍然存在，只是不再作为结构事实的来源。
        """
        if not profile.template_dir_src:
            return
        s_ns, _, s_rel = profile.template_dir_src.partition("/")
        src_root = pack_data(pack_dir) / s_ns / s_rel
        for path in sorted(p for p in src_root.rglob("*.snbt") if p.is_file()):
            record(
                store,
                rel_posix(path, pack_dir),
                FAMILY,
                status=LedgerStatus.CLASSIFIED_SKIP,
                rule="结构模板改读服务端 jar 内层第一手",
            )

    def _one(self, path: Path, base: Path, store: FactStore, input_kind: str) -> None:
        file_label = rel_posix(path, base)
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            doc = parse_snbt(text)
        except (OSError, SnbtError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是 compound")
            return

        payload, missing = normalize_template(doc, template_id_from_file(file_label))

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="template",
                payload=payload,
                prov=Prov(input=input_kind, file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, missing=tuple(missing))
