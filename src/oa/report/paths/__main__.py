"""`python -m oa.report.paths` 的入口，等同于 `oa-paths`。"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
