"""交易对价的形状：`wants` 一律是数组，附魔书报价给价格区间。

数据里附魔书写的是 `wants.count = 0`（真实价格由 `enchant_randomly` 的附魔
等级决定）。这条测试钉住两件事：

1. **形状统一**：`wants` 是数组，不混用对象/数组；
2. **对价不再空**：带 `include_additional_cost_component` 的报价给出区间，
   区间由加价公式与附魔等级算出，不是拍一个绝对值。
"""

from __future__ import annotations

import unittest

from tests.support import pack, store, why


class _TradePriceBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.offers = [
            fact.payload
            for fact in store(cls.label).of_kind("trade")
            if fact.payload.get("layer") == "offer"
        ]

    def test_wants_is_always_a_list(self) -> None:
        for payload in self.offers:
            self.assertIsInstance(payload["wants"], list, payload["trade"])

    def test_counts_are_numbers_or_ranges(self) -> None:
        for payload in self.offers:
            for want in payload["wants"]:
                count = want["count"]
                if isinstance(count, dict):
                    self.assertEqual(set(count), {"min", "max"}, payload["trade"])
                    self.assertLessEqual(count["min"], count["max"])
                else:
                    self.assertIsInstance(count, int)
                    self.assertGreaterEqual(count, 0)

    def test_enchant_price_model(self) -> None:
        priced = [payload for payload in self.offers if payload.get("price_model")]
        self.assertTrue(priced, "附魔书报价应当带 price_model")
        for payload in priced:
            model = payload["price_model"]
            self.assertEqual(model["kind"], "enchant_randomly")
            self.assertIn("formula", model)
            self.assertEqual(model["levels"]["min"], 1)
            self.assertGreaterEqual(model["levels"]["max"], 1)
            self.assertGreater(model["clamp"], 0)
            count = payload["wants"][0]["count"]
            self.assertIsInstance(count, dict, payload["trade"])
            self.assertGreater(count["min"], 0, payload["trade"])
            self.assertLessEqual(count["max"], model["clamp"])


@unittest.skipUnless(pack("26.3"), why("26.3"))
class TradePrice263Test(_TradePriceBase, unittest.TestCase):
    label = "26.3"

    def test_librarian_books_are_priced(self) -> None:
        books = [
            payload
            for payload in self.offers
            if payload.get("profession") == "librarian"
            and payload["gives"]["id"] == "minecraft:enchanted_book"
        ]
        self.assertEqual({payload["level"] for payload in books}, {1, 2, 3, 4})
        for payload in books:
            count = payload["wants"][0]["count"]
            self.assertEqual(count, {"min": 5, "max": 64}, payload["trade"])
            self.assertEqual(
                payload["additional_wants"],
                [{"count": 1, "id": "minecraft:book"}],
            )

    def test_plain_offers_keep_integer_counts(self) -> None:
        plain = [
            payload
            for payload in self.offers
            if payload.get("profession") == "armorer"
            and payload["trade"].endswith("emerald_iron_boots")
        ]
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0]["wants"], [{"count": 4, "id": "minecraft:emerald"}])
        self.assertNotIn("price_model", plain[0])


if __name__ == "__main__":
    unittest.main()
