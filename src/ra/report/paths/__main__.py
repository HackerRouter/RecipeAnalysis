"""`python -m ra.report.paths` 的入口，等同于 `ra-paths`。"""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
