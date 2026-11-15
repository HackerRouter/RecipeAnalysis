"""交易参数（经验值、使用次数、价格浮动）与共用条目分组。

判据：

- 参数按构造器体里的字段赋值回取，不按形参名字猜（反编译后是 n/n2/n3）
- 只做委托的重载按位置回溯到被委托构造器
- 共用条目目录不记职业，记共享分组（分组名从标签目录读）
"""

from __future__ import annotations

import unittest

from ra.adapters.source.idioms.trades import (
    _param_meta,
    offer_params,
    offers_to_links,
)

VILLAGER_TRADES_JAVA = """
public class VillagerTrades {
    static class EmeraldForItems implements ItemListing {
        private final Item item;
        private final int cost;
        private final int maxUses;
        private final int villagerXp;
        private final float priceMultiplier;

        public EmeraldForItems(ItemLike itemLike, int n, int n2, int n3) {
            this.item = itemLike.asItem();
            this.cost = n;
            this.maxUses = n2;
            this.villagerXp = n3;
            this.priceMultiplier = 0.05f;
        }
    }

    static class ItemsForEmeralds implements ItemListing {
        private final ItemStack itemStack;
        private final int emeraldCost;
        private final int numberOfItems;
        private final int maxUses;
        private final int villagerXp;
        private final float priceMultiplier;

        public ItemsForEmeralds(Item item, int n, int n2, int n3) {
            this(new ItemStack(item), n, n2, 12, n3);
        }

        public ItemsForEmeralds(ItemStack itemStack, int n, int n2, int n3, int n4) {
            this.itemStack = itemStack;
            this.emeraldCost = n;
            this.numberOfItems = n2;
            this.maxUses = n3;
            this.villagerXp = n4;
            this.priceMultiplier = 0.05f;
        }
    }
}
"""


class OfferParamsTest(unittest.TestCase):
    def test_direct_assignment(self) -> None:
        params = offer_params(VILLAGER_TRADES_JAVA)
        self.assertEqual(
            params[("EmeraldForItems", 4)],
            {
                "max_uses": ("arg", 2),
                "xp": ("arg", 3),
                "price_multiplier": ("const", 0.05),
            },
        )

    def test_delegate_is_traced_by_position(self) -> None:
        """4 参重载只做委托：maxUses 固定成 12，xp 回溯到第 4 个形参。"""
        params = offer_params(VILLAGER_TRADES_JAVA)
        self.assertEqual(
            params[("ItemsForEmeralds", 4)],
            {
                "max_uses": ("const", 12),
                "xp": ("arg", 3),
                "price_multiplier": ("const", 0.05),
            },
        )

    def test_resolve_against_call_args(self) -> None:
        params = offer_params(VILLAGER_TRADES_JAVA)
        meta = _param_meta("EmeraldForItems", ["Items.WHEAT", "20", "16", "2"], params)
        self.assertEqual(meta, {"max_uses": 16, "xp": 2, "price_multiplier": 0.05})

    def test_unparsable_argument_is_reported_not_guessed(self) -> None:
        params = offer_params(VILLAGER_TRADES_JAVA)
        meta = _param_meta("EmeraldForItems", ["Items.WHEAT", "20", "16", "someVar"], params)
        self.assertEqual(meta["unresolved_xp"], "someVar")
        self.assertNotIn("xp", meta)

    def test_meta_lands_on_links(self) -> None:
        params = offer_params(VILLAGER_TRADES_JAVA)
        links = offers_to_links(
            ("EmeraldForItems", ["Items.WHEAT", "20", "16", "2"]),
            "farmer",
            1,
            params,
        )
        self.assertEqual(links[0].meta["xp"], 2)
        self.assertEqual(links[0].meta["max_uses"], 16)

    def test_unknown_class_yields_no_params(self) -> None:
        params = offer_params(VILLAGER_TRADES_JAVA)
        self.assertEqual(_param_meta("NoSuchTrade", ["1", "2"], params), {})


if __name__ == "__main__":
    unittest.main()
