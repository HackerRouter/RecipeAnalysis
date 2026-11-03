"""测试共用的摄取缓存与版本过滤。

缓存键是版本标签，值是**只读**的摄入结果，跨测试类共享。一次完整 ingest 要扫
7301（26.3）/ 4236（1.18.2）个 Java 文件、解析上千个 JSON；十几个测试类各自重跑
是几分钟，共享后是全量 65 秒。

要验证 ingest 本身幂等性的测试应当绕过本模块直接调用，不要在这里加 `force`
开关——那会让缓存悄悄失效，问题又回到「慢得跑不动」。

`--label` 过滤、跳过理由、版本清单的用法见 [`tests/README.md`](README.md)。
"""

from __future__ import annotations

import os
from pathlib import Path

from oa.adapters import audit_tree, run_adapters, skip_inert_registries, sweep_assets
from oa.facts import FactStore
from oa.inputs import ensure_reports, ensure_structures, load_manifest
from oa.paths import cache_root, input_pack, repo_root
from oa.probe import build_profile
from oa.probe.registries import Registries

ROOT = repo_root()

_stores: dict[str, FactStore] = {}
_profiles: dict[str, object] = {}
_audits: dict[str, tuple[FactStore, list[str]]] = {}


def _version_key(label: str) -> tuple[int, ...]:
    """按版本号数值排序用。非数字标签排到最后。"""
    try:
        return tuple(int(part) for part in label.split("."))
    except ValueError:
        return (-1,)


def known_labels() -> tuple[str, ...]:
    """`inputs/` 下所有版本目录，新版本在前。

    **扫描而不是硬编码**：加版本只需放输入包目录，不改测试代码。
    """
    base = ROOT / "inputs"
    if not base.is_dir():
        return ()
    found = [child.name for child in base.iterdir() if child.is_dir()]
    return tuple(sorted(found, key=_version_key, reverse=True))


def chosen_labels() -> frozenset[str]:
    """当前筛选的版本。空集表示全选。

    值来自 `pytest --label`（由 `conftest.py` 写入）或环境变量 `OA_LABELS`。
    """
    raw = os.environ.get("OA_LABELS", "").strip()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def selected(label: str) -> bool:
    """该版本是否被选中。无筛选时全选。"""
    chosen = chosen_labels()
    return not chosen or label in chosen


def _screen() -> str:
    """报错时展示当前的筛选值，不写变量名——入口可能是 `--label` 也可能是环境变量。"""
    return "、".join(sorted(chosen_labels())) or "全部"


def why(label: str) -> str:
    """`skipUnless` 的理由。区分「没选中」与「包不存在」——两者混为一谈会误判成包丢了。"""
    if not selected(label):
        return f"未选中 {label}（筛选：{_screen()}）"
    return f"输入包 {label} 不存在，跳过"


def why_all(labels: tuple[str, ...]) -> str:
    """跨版本测试的理由：列出缺的版本，并说明是被过滤还是包不齐。"""
    missing = [label for label in labels if not selected(label)]
    if missing:
        return f"未选中 {', '.join(missing)}（筛选：{_screen()}）"
    absent = [label for label in labels if pack(label) is None]
    if absent:
        return f"输入包 {', '.join(absent)} 不存在，跳过"
    return "版本齐备"


def pack(label: str) -> Path | None:
    """输入包路径；目录不在或未选中时返回 None（供 `skipUnless` 用）。"""
    if not selected(label):
        return None
    path = input_pack(ROOT, label)
    return path if path.is_dir() else None


def require(label: str) -> Path:
    path = pack(label)
    if path is None:
        raise unittest_skip(f"输入包 {label} 不存在")
    return path


def unittest_skip(reason: str) -> Exception:
    import unittest

    return unittest.SkipTest(reason)


def profile(label: str):
    """探测结果，缓存。"""
    if label not in _profiles:
        target = require(label)
        manifest = load_manifest(target)
        reports = ensure_reports(manifest, cache_root(ROOT))
        structures = ensure_structures(manifest, cache_root(ROOT))
        registries = Registries.load(reports.root / "registries.json")
        _profiles[label] = build_profile(
            target, manifest, reports, registries, structures
        )
    return _profiles[label]


def store(label: str) -> FactStore:
    """完整摄入结果（台账 + 事实 + 对账），缓存。"""
    if label not in _stores:
        target = require(label)
        fact_store = FactStore(label=label)
        probe = profile(label)
        skip_inert_registries(probe, target, fact_store)
        sweep_assets(target, fact_store)
        run_adapters(probe, target, fact_store)
        _stores[label] = fact_store
    return _stores[label]


def audited(label: str) -> tuple[FactStore, list[str], dict]:
    """额外跑全树审计，返回 `(store, 未交代文件列表)`。

    **不复用 `store()` 的实例**：`audit_tree` 会往台账里加行，共用会让先读到
    缓存的测试看到多出来的行，测试结果就取决于执行顺序。
    代价是这一条路径自己再摄一次，但它只有一个测试类用。
    """
    if label not in _audits:
        target = require(label)
        fact_store = FactStore(label=label)
        probe = profile(label)
        skip_inert_registries(probe, target, fact_store)
        sweep_assets(target, fact_store)
        run_adapters(probe, target, fact_store)
        unaccounted = audit_tree(probe, target, fact_store)
        _audits[label] = (fact_store, unaccounted)
    return _audits[label]
