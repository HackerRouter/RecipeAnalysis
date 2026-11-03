"""来源族：一个输入形状一个模块。

族的分法：`recipes` / `loot` / `trades` / `worldgen` / `bindings` / `code` / `overlay`。
本期实现 `recipes`、`loot`、`trades`、`worldgen`、`code` 五族；
`bindings` 由既有的 `template`/`code_link` 事实覆盖，`overlay` 等地形包阶段。
"""

from __future__ import annotations
