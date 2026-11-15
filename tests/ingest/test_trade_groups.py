"""共用交易条目：目录首段不一定是职业。

`villager_trade/smith/` 的 3 条交易被盔甲匠、工具匠、武器匠通过
`#minecraft:common_smith/level_N` 共同引用。把它记成职业会让下游按职业
汇总时读出一个不存在的 `smith`。
"""

from __future__ import annotations

import unittest

from tests.support import pack, store, why

SHARED_SEGMENT = "smith"
SHARED_GROUP = "common_smith"


@unittest.skipUnless(pack("26.3"), why("26.3"))
class SharedTradeGroupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = [
            fact.payload
            for fact in store("26.3").of_kind("trade")
            if fact.payload.get("layer") == "offer"
        ]

    def shared(self) -> list[dict]:
        return [row for row in self.rows if row.get("shared_group")]

    def test_shared_rows_have_no_profession(self) -> None:
        shared = self.shared()
        self.assertTrue(shared, "共用条目没有被识别")
        for row in shared:
            self.assertIsNone(row["profession"], row["trade"])
            self.assertEqual(row["shared_group"], SHARED_GROUP, row["trade"])

    def test_shared_rows_are_the_smith_directory(self) -> None:
        self.assertEqual(
            {row["trade"].split(":", 1)[1].split("/")[0] for row in self.shared()},
            {SHARED_SEGMENT},
        )

    def test_shared_rows_resolve_to_real_professions(self) -> None:
        """共用条目按交易组的引用方向展开成真实职业，不靠目录名猜。"""
        expected = {"armorer", "toolsmith", "weaponsmith"}
        for row in self.shared():
            applies = row.get("applies_to") or []
            self.assertEqual({entry["profession"] for entry in applies}, expected, row["trade"])
            tops = {entry["level"] for entry in applies}
            self.assertEqual(len(tops), 1, row["trade"])
            self.assertIn(tops.pop(), (1, 2))

    def test_shared_rows_have_no_fake_profession(self) -> None:
        for row in self.rows:
            if row.get("shared_group"):
                continue
            self.assertNotEqual(row.get("profession"), SHARED_SEGMENT, row["trade"])

    def test_every_other_row_has_a_profession(self) -> None:
        for row in self.rows:
            if row.get("shared_group"):
                continue
            self.assertTrue(row.get("profession"), row["trade"])

    def test_profession_set_matches_trade_sets(self) -> None:
        """职业全集应与 `trade_set/` 的目录一致（14 个，不含 smith）。"""
        professions = {row["profession"] for row in self.rows if row.get("profession")}
        self.assertEqual(len(professions), 14, sorted(professions))
        self.assertNotIn(SHARED_SEGMENT, professions)


@unittest.skipUnless(pack("26.3"), why("26.3"))
class TradeDefaultTest(unittest.TestCase):
    """数据里没写的字段按 `VillagerTrade.CODEC` 的默认值补上。

    不补的话，下游读不到 `xp` 会把默认 1 当成 0——差一整档经验。
    """

    CODEC_DEFAULTS = {"max_uses": 4, "xp": 1, "reputation_discount": 0.0}

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = [
            fact.payload
            for fact in store("26.3").of_kind("trade")
            if fact.payload.get("layer") == "offer"
        ]

    def test_every_offer_has_xp(self) -> None:
        for row in self.rows:
            self.assertIn("xp", row["meta"], row["trade"])

    def test_defaults_match_codec(self) -> None:
        for row in self.rows:
            meta = row["meta"]
            for key in meta.get("defaults") or ():
                self.assertIn(key, self.CODEC_DEFAULTS, row["trade"])
                self.assertEqual(meta[key], self.CODEC_DEFAULTS[key], row["trade"])

    def test_explicit_values_are_not_listed_as_defaults(self) -> None:
        """显式写了 1 与缺省得到 1 是两件事，`defaults` 只列后者。"""
        explicit = [
            row for row in self.rows
            if "xp" not in (row["meta"].get("defaults") or ())
        ]
        self.assertTrue(explicit, "应当有显式写 xp 的交易")
        for row in explicit:
            self.assertNotIn("xp", row["meta"].get("defaults") or (), row["trade"])


if __name__ == "__main__":
    unittest.main()
