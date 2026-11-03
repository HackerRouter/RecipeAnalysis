"""pytest 配置：给测试加 `--label`。

unittest 的 argparse 没有自定义参数的扩展点，只能靠环境变量 `OA_LABELS`；
pytest 有 `pytest_addoption`，所以这里是「参数优先、环境变量兜底」。

时机很关键：各测试模块的 `skipUnless(_pack("26.3"), ...)` 在**模块导入时**求值，
版本过滤必须在 collection 之前生效。`pytest_configure` 早于 collection，是能保证
这一点的钩子；放在 `pytest_collection_modifyitems` 里就晚了。
"""

from __future__ import annotations

import os

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--label",
        action="store",
        default=None,
        metavar="LABELS",
        help="只跑这些版本，逗号分隔（如 26.3 或 26.3,1.18.2）；不给则读 OA_LABELS，否则全选",
    )


def pytest_configure(config: pytest.Config) -> None:
    labels = config.getoption("label")
    if labels:
        os.environ["OA_LABELS"] = labels
