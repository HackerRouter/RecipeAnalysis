"""探测结果事实化，并登记本期不做的族。

## 为什么 `profile` 要是事实

`profile` 是事实种类之一（见 `facts/schema.py` 的 `KINDS`）。理由是它决定了每个适配器走哪条分派分支——
「这套事实是在 `loot_dialect=modern`、`components_layout=components` 这些结论下产出的」。
把它写进事实流，意味着下游能只凭事实复算出「当时为什么这样解析」，
而不必去读一个游离在事实流之外的 JSON 快照。

`prov.file` 记数据包内的 `data/` 相对路径，`prov.input = "src"`：探测的判据全部来自
输入包本身（数据包目录形状 + 运行期导出的注册表键集合）。

## 为什么 `pack_delta` 现在必然为空

地形包 overlay 本期不接，暂缓。但「没有地形包」不能靠
「这类事实一条也没有」来表达——那与「实现漏了」在产物上无法区分。
按红线 3（扫描不到的东西不得静默跳过，必须显式登记），这里落一条族级不可用说明。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, Prov
from ..probe.profile import Profile
from .base import Adapter

# 探测的判据来自数据包目录形状，所以 prov.file 指向数据包根
PROV_FILE = "data/"


class ProfileAdapter(Adapter):
    id = "src/profile"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        payload = profile.as_json()
        # 完整 Profile 已在 profile.json 里；事实只承载「决定分派」的那些判定，
        # 避免两个地方各存一份全量而慢慢分叉。
        store.add(
            Fact(
                kind="profile",
                payload={
                    "label": payload["label"],
                    "content_commit": payload["content_commit"],
                    "source_repo": payload["source_repo"],
                    "version": payload["version"],
                    "loot_dialect": payload["loot_dialect"],
                    "worldgen_source": payload["worldgen"]["source"],
                    "worldgen_counts": payload["worldgen"]["counts"],
                    "components_layout": payload["reports"]["components_layout"],
                    "datapack_capability": payload["reports"]["datapack_capability"],
                    "dirs": {
                        registry: claim["path"]
                        for registry, claim in payload["dirs"].items()
                    },
                    "template_dir": payload["templates"]["dir"],
                    "notes_count": len(payload["notes"]),
                    "unresolved_count": len(payload["unresolved"]),
                },
                prov=Prov(input="src", file=PROV_FILE, ptr=""),
            )
        )

        # 本期不接地形包，显式登记而非静默缺失
        store.mark_unavailable(
            "pack_delta",
            "本次输入不含地形包",
            "无 packs/ 输入时该族不产出，不代表实现缺失",
        )
