"""运行期导出适配器：默认组件。

每个物品的默认组件是推导「item↔block」「工具能力」「变体维度」的共同前提，
所以必须落成事实，不能只当作探测到的一个目录存在性。

**「不具有某组件」的两种表达**，两种都要认，但语义必须区分清楚：

| 版本 | 表达方式 | 实测 |
|---|---|---|
| 26.3 | 键**缺席**即不具有（1658 个物品各只有 13–20 个组件） | 全库 `!` 前缀 0 处 |
| 早期方案预期 | `!minecraft:X` 表示不具有 | 本版未出现，仍需支持 |

把 `!minecraft:X` 读成「具有该组件且值为空对象」是这里的核心风险：
下游据此判定「该组件不是常量」时会多出一批假维度。因此带 `!` 的键
一律进 `absent`，绝不进 `components`。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix

FAMILY = "components"

NEGATION_PREFIX = "!"


def split_components(raw: object) -> tuple[dict, list[str], list[str]]:
    """拆成（具有的组件, 明确不具有的组件, 问题）。

    只接受对象。`!` 前缀的键进 absent，不进 components。
    """
    if raw is None:
        return {}, [], ["缺少 components"]
    if not isinstance(raw, dict):
        return {}, [], [f"components 不是对象，是 {type(raw).__name__}"]

    present: dict = {}
    absent: list[str] = []
    problems: list[str] = []

    for key, value in raw.items():
        if not isinstance(key, str):
            problems.append(f"组件键不是字符串：{key!r}")
            continue
        if key.startswith(NEGATION_PREFIX):
            name = key[len(NEGATION_PREFIX) :]
            if not name:
                problems.append("`!` 后没有组件名")
                continue
            absent.append(name)
            # 值必须视为无意义：`!X: {}` 不代表 X 存在且为空
            continue
        present[key] = value

    if present.keys() & set(absent):
        problems.append("同一组件同时出现带 `!` 与不带 `!` 的写法")

    return present, absent, problems


class ComponentsAdapter(Adapter):
    id = "jar/components"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        if profile.reports_root is None or profile.components_dir is None:
            store.mark_unavailable(
                FAMILY,
                "该版本无默认组件报告",
                "1.20.5 引入组件系统后才有此报告；变体维度推导将退回旧路径",
            )
            return

        root = Path(profile.reports_root) / profile.components_dir
        if not root.is_dir():
            record(
                store,
                profile.components_dir,
                FAMILY,
                status=LedgerStatus.FAILED,
                error="探测给出的默认组件目录不存在",
            )
            return

        reports_root = Path(profile.reports_root)
        marker_seen = False
        for path in iter_json_files(root):
            seen = self._one(path, reports_root, store)
            marker_seen = marker_seen or seen

        if not marker_seen:
            profile.notes.append(
                "默认组件报告未使用 `!` 前缀表达「不具有」；"
                "该版本以键缺席表达，`absent` 字段一律为空"
            )

    def _one(self, path: Path, reports_root: Path, store: FactStore) -> bool:
        file_label = f"reports/{path.relative_to(reports_root).as_posix()}"
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return False

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return False

        unknown_keys = [k for k in doc if k != "components"]
        present, absent, problems = split_components(doc.get("components"))

        missing: list[str] = []
        if problems:
            missing.append("组件集有无法解析的项")
        if unknown_keys:
            missing.append(f"顶层未知字段 {', '.join(sorted(unknown_keys))}")

        payload = {
            "item": _item_id(file_label),
            "components": present,
            "absent": absent,
            "count": len(present),
            "negation_marker": bool(absent),
        }
        if problems:
            payload["problems"] = problems

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="components",
                payload=payload,
                prov=Prov(input="jar", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1)
        return bool(absent)


def _item_id(file_label: str) -> str:
    """`reports/minecraft/components/item/iron_ingot.json` → `minecraft:iron_ingot`。

    命名空间是 `components/item/` 前的那一段；条目路径可能带子目录，
    因此取相对 item 目录的完整路径。
    """
    marker = "/components/item/"
    if marker in file_label:
        head, _, tail = file_label.partition(marker)
        namespace = head.rsplit("/", 1)[-1]
        return f"{namespace}:{tail[:-5]}"
    return file_label[:-5]
