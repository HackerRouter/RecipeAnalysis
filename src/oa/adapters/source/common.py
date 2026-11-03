"""反编译源码族的共享标识。

`FAMILY` 与 `JAVA_PREFIX` 被适配器主体与后验校验两边使用，单独立一处，
免得拆出 `verify.py` 时形成循环导入。
"""

from __future__ import annotations

# 事实族名与台账行的路径前缀。
FAMILY = "code"
JAVA_PREFIX = "src/main/java"

__all__ = ["FAMILY", "JAVA_PREFIX"]
