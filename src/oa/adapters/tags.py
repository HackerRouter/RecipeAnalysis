"""数据包适配器：标签。

标签值有三种写法，全部是合法输入，都要认：
- 字符串 `"minecraft:iron_ingot"`
- 对象 `{"id": "minecraft:iron_ingot", "required": false}`
- 嵌套引用 `"#minecraft:planks"`（指向另一个标签，不是注册表条目）

`required` 语义属 IR（是否硬前置），这里只如实记录。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "tags"


def normalize_values(raw: object) -> tuple[list[str], list[str], list[dict] | None]:
    """拆成（直接条目, 嵌套标签, 问题列表）。问题列表非空即 partial。"""
    if raw is None:
        return [], [], ["缺少 values"]
    if not isinstance(raw, list):
        return [], [], [f"values 不是数组，是 {type(raw).__name__}"]

    direct: list[str] = []
    nested: list[str] = []
    problems: list[dict] = []

    for index, item in enumerate(raw):
        if isinstance(item, str):
            ident = item
        elif isinstance(item, dict):
            ident = item.get("id")
            if not isinstance(ident, str):
                problems.append({"index": index, "why": "对象缺少 id"})
                continue
        else:
            problems.append({"index": index, "why": f"值类型 {type(item).__name__}"})
            continue

        if ident.startswith("#"):
            nested.append(ident[1:])
        else:
            direct.append(ident)

    return direct, nested, (problems or None)


class TagAdapter(Adapter):
    id = "src/tags"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        data_root = pack_data(pack_dir)
        for registry, tag_dir in sorted(profile.tag_dirs.items()):
            ns, _, rel = tag_dir.path.partition("/")
            root = data_root / ns / rel
            if not root.is_dir():
                record(
                    store,
                    tag_dir.path,
                    FAMILY,
                    status=LedgerStatus.FAILED,
                    error="探测给出的标签目录不存在",
                )
                continue
            for path in iter_json_files(root):
                self._one(path, root, pack_dir, registry, store)

    def _one(
        self, path: Path, tag_root: Path, pack_dir: Path, registry: str, store: FactStore
    ) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            from ..util.jsonio import read_json

            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return

        unregistered = [key for key in doc if key not in ("values", "replace")]
        direct, nested, problems = normalize_values(doc.get("values"))

        missing: list[str] = []
        if problems:
            missing.append("values 有无法解析的项")
        if unregistered:
            missing.append(f"未知字段 {', '.join(sorted(unregistered))}")

        payload = {
            "registry": registry,
            "tag": _tag_id(path, tag_root),
            "values": direct,
            "nested": nested,
            "replace": bool(doc.get("replace", False)),
        }
        if problems:
            payload["problems"] = problems

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="tag",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1)


def _tag_id(path: Path, tag_root: Path) -> str:
    """标签 ID **不含**注册表子目录。

    实测依据：配方里写 `#minecraft:planks`（不是 `#minecraft:item/planks`），
    worldgen 里写 `#minecraft:features_cannot_replace`（不是 `#minecraft:worldgen/feature/...`）。

    `<ns>/tags/<注册表路径>/<标签路径>.json` → `<ns>:<标签路径>`，
    注册表路径的段数随注册表变（`item` 一段、`worldgen/biome` 两段），
    所以用「相对标签目录」算，不靠切分字符串。
    """
    rel = path.relative_to(tag_root).with_suffix("").as_posix()
    return f"{_namespace(path)}:{rel}"


def _namespace(path: Path) -> str:
    """从 `.../data/<ns>/tags/...` 里取命名空间。"""
    parts = path.parts
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] == "data" and index + 1 < len(parts):
            return parts[index + 1]
    return "minecraft"
