"""知识表的加载与格式校验。

`knowledge/` 的目录结构见 `knowledge/README.md`。本模块是唯一的读取方，
路径一律走 `paths.py` 的 `knowledge_*` 访问器，不在这里拼字符串。

## 两种失败方式

**硬失败**（`KnowledgeError`）：表缺失、顶层不是对象、值不在允许集合内。
这类知识的缺失会让判定失真——未登记的条件若默认当成「无前置」，需要设备的
物品会被误判为可徒手获得。

**软失败**（返回空字典）：只有例外表。它是「解释层」的增强，缺它时
`no_rule` 退化成笼统桶，归因仍然完整，只是把「确定拿不到」与「尚未提取」
混在一起。此时打印一行提示，不中止。
"""

from __future__ import annotations

import fnmatch
import json
import tomllib
from pathlib import Path

from ..paths import knowledge_assumptions, knowledge_exceptions, knowledge_map

# `knowledge/maps/` 下的分类目录。知识按「回答什么问题」分层，目录名即层级，
# 不靠文件名前缀区分。
VOCABULARY = "vocabulary"
MECHANISM = "mechanism"
EXCEPTIONS = "exceptions"


class KnowledgeError(RuntimeError):
    """知识表缺失或格式不对。"""


__all__ = [
    "EXCEPTIONS",
    "MECHANISM",
    "VOCABULARY",
    "KnowledgeError",
    "load_assumptions",
    "load_condition_kinds",
    "load_exceptions",
    "load_map",
]


def load_assumptions(root: Path) -> list[str]:
    """读分析前提，返回启用的 `assume:*` 节点。

    `survival = false` 的条目视为不成立，不进播种集但保留在文件里供审查。
    """
    path = knowledge_assumptions(root)
    if not path.is_file():
        raise KnowledgeError(f"缺少假设清单：{path}")
    with path.open("rb") as handle:
        doc = tomllib.load(handle)
    assumes = doc.get("assumes")
    if not isinstance(assumes, dict) or not assumes:
        raise KnowledgeError(f"{path} 没有 [assumes.*] 段")
    seeds: list[str] = []
    for name, entry in assumes.items():
        if not isinstance(entry, dict):
            raise KnowledgeError(f"{path}: assumes.{name} 不是表")
        target = entry.get("node")
        if not isinstance(target, str):
            raise KnowledgeError(f"{path}: assumes.{name} 缺 node")
        if entry.get("survival", True):
            seeds.append(target)
    return sorted(set(seeds))


def load_map(root: Path, category: str, name: str) -> dict:
    """读 `knowledge/maps/<分类>/<表名>.json`。缺文件即硬失败。

    `_` 前缀的键是说明或私有数据（`_about`、`_patterns`），不参与匹配，这里滤掉。
    """
    path = knowledge_map(root, category, name)
    if not path.is_file():
        raise KnowledgeError(f"缺少知识表：{path}")
    with path.open(encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise KnowledgeError(f"{path} 顶层应为对象")
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def load_condition_kinds(root: Path) -> dict[str, str]:
    """战利品条件 → 判定类别。值不在允许集合内即硬失败。"""
    raw = load_map(root, VOCABULARY, "condition_kinds")
    allowed = {"hard", "soft", "meta_probability", "ignore", "unresolved", "combinator"}
    bad = {k: v for k, v in raw.items() if v not in allowed}
    if bad:
        raise KnowledgeError(f"condition_kinds 出现非法类别：{bad}")
    return raw


def load_exceptions(root: Path, universe: list[str] | None = None) -> dict[str, dict]:
    """读例外表并展开 `_patterns`，返回 `{裸名: {category, basis}}`。

    `_patterns` 表达成片规律（如 88 个刷怪蛋全是创造专属），避免把同一条依据
    抄 88 遍——逐条列举正是「不写逐物品白名单」要避免的。

    通配需要枚举对象，所以只在给了全集时展开；`items` 形式的显式列表不依赖它。
    """
    path = knowledge_exceptions(root)
    if not path.is_file():
        print("提示：未找到例外表，no_rule 将不区分类别")
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"错误：例外表读取失败：{exc}")
        return {}
    if not isinstance(doc, dict):
        print("错误：例外表顶层应为对象")
        return {}

    table = {k: v for k, v in doc.items() if not k.startswith("_")}
    for pattern in doc.get("_patterns") or []:
        if not isinstance(pattern, dict):
            continue
        entry = {
            "category": pattern.get("category", "未分类"),
            "basis": pattern.get("basis", ""),
        }
        for name in pattern.get("items") or []:
            table.setdefault(name, entry)
        glob = pattern.get("match")
        if isinstance(glob, str) and universe:
            for node in universe:
                bare = node.split(":", 1)[-1]
                if fnmatch.fnmatch(bare, glob):
                    table.setdefault(bare, entry)
    return table
