"""流体桶内容节点的注册表对账。

`Fluids.WATER` → `block:minecraft:water` 是按常量小写推出来的，属推断。
`Fluids` 里的 `FLOWING_WATER` 不是方块，推出来的名字在注册表里不存在：
留着它，那个桶的 body 就带一个恒假节点，整条规则失效而没有任何报错。

两条分支都要覆盖：

- 名字命中 → 事实原样保留
- 名字落空 → 只摘掉那个 `via`，桶仍由空桶成立，且留一条台账
"""

from __future__ import annotations

import unittest

from ra.adapters.source.verify import verify_fluid_bucket_blocks
from ra.facts import Fact, FactStore, LedgerStatus, Prov


def _store(via: list[str], blocks: tuple[str, ...] = ("minecraft:water",)) -> FactStore:
    store = FactStore(label="test")
    store.add(
        Fact(
            kind="registry",
            payload={"registry": "minecraft:block", "entries": list(blocks)},
            prov=Prov(input="src", file="data/minecraft/blocks.json"),
        )
    )
    store.add(
        Fact(
            kind="code_link",
            payload={
                "idiom": "fluid_buckets",
                "link": {
                    "head": "item:minecraft:water_bucket",
                    "kind": "yield",
                    "via": list(via),
                    "inputs": ["item:minecraft:bucket"],
                    "soft": [],
                },
                "meta": {"content_kind": "fluid", "content": "WATER"},
            },
            prov=Prov(input="src", file="Items.java", ptr="Items#WATER_BUCKET"),
        )
    )
    return store


def _only_link(store: FactStore) -> Fact:
    links = store.of_kind("code_link")
    assert len(links) == 1, links
    return links[0]


class VerifyFluidBucketBlocksTest(unittest.TestCase):
    def test_block_in_registry_is_kept(self) -> None:
        store = _store(["block:minecraft:water"])
        verify_fluid_bucket_blocks(store)
        link = _only_link(store).payload["link"]
        self.assertEqual(link["via"], ["block:minecraft:water"])
        self.assertEqual(store.ledger.rows, [])

    def test_unknown_block_is_dropped_and_recorded(self) -> None:
        store = _store(["block:minecraft:flowing_water"])
        verify_fluid_bucket_blocks(store)
        fact = _only_link(store)
        self.assertEqual(fact.payload["link"]["via"], [])
        self.assertEqual(fact.payload["meta"]["via_dropped"], ["block:minecraft:flowing_water"])
        # 空桶那层仍然成立：事实不剔除
        self.assertEqual(fact.payload["link"]["inputs"], ["item:minecraft:bucket"])

        rows = [row for row in store.ledger.rows if row.status is LedgerStatus.CLASSIFIED_SKIP]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rule, "流体桶的内容名推不出方块")
        self.assertIn("flowing_water", rows[0].note)

    def test_missing_registry_skips(self) -> None:
        """上游没产出注册表时跳过，不当成全部落空。"""
        store = FactStore(label="test")
        store.add(
            Fact(
                kind="code_link",
                payload={
                    "idiom": "fluid_buckets",
                    "link": {
                        "head": "item:minecraft:water_bucket",
                        "kind": "yield",
                        "via": ["block:minecraft:water"],
                        "inputs": ["item:minecraft:bucket"],
                        "soft": [],
                    },
                    "meta": {},
                },
                prov=Prov(input="src", file="Items.java"),
            )
        )
        verify_fluid_bucket_blocks(store)
        self.assertEqual(_only_link(store).payload["link"]["via"], ["block:minecraft:water"])


if __name__ == "__main__":
    unittest.main()
