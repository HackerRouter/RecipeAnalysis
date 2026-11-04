"""探测器的共用工具与小常量。

被 `datapack`、`worldgen`、`loot` 三组共用，单独立一处避免子模块反向
import `build.py` 形成循环。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..util.jsonio import read_json

# 单目录采样上限。目录里可能有上千个同类文件，全读只为判形状不值当。
SAMPLE_LIMIT = 60

# 判形状时的最低一致率。低于它说明目录里是混合内容，不算某个形状的归属。
SHAPE_MIN = 0.5

__all__ = ["SAMPLE_LIMIT", "SHAPE_MIN", "load_json_safe", "sample"]


def sample(paths: list[Path], limit: int = SAMPLE_LIMIT) -> list[Path]:
    """均匀采样，避免只看到同一子目录。"""
    if len(paths) <= limit:
        return paths
    step = len(paths) / limit
    return [paths[int(i * step)] for i in range(limit)]


def load_json_safe(path: Path) -> object | None:
    """读不动就返回 None。探测阶段用，失败由调用方记 UNRESOLVED。"""
    try:
        return read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
