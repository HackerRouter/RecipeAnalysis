"""错误分类。硬失败一律抛出，不用返回值表示，避免上游静默降级。"""

from __future__ import annotations


class RaError(Exception):
    """本项目错误的基类。"""


class InputError(RaError):
    """输入包不完整或 provenance 不可复算。"""


class ProbeError(RaError):
    """探测无法给出 Profile，或探测结果与期望冲突。"""


class AdapterError(RaError):
    """适配器遇到未知结构：不忽略、不猜测。"""
