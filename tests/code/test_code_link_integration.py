"""code_link 的集成测试：跨版本等价性。

这是整个 code_link 设计最硬的验证：**同一机制在两种实现形态下，
最终可得物品集合必须一致**。

- 1.18.2：16 条 `yield`，代码里静态映射 `DyeColor → Blocks.*_WOOL`
- 26.3：1 条 `holds`（羊 → 分发器表），子表在数据包里产同样 16 种羊毛

两版都从输入包现场抽取，不依赖任何预置答案。
"""

from __future__ import annotations

import unittest
from collections import Counter

from ra.facts import FactStore


def _ingest(label: str, pack) -> tuple[FactStore, object]:
    """走共享缓存：完整 ingest 约 20 秒，本文件有 7 处调用点，不能各跑一次。"""
    from tests.support import profile, store

    return store(label), profile(label)


def _pack(label: str):
    return pack(label)


from tests.support import pack, why, why_all

class _ShearBase(unittest.TestCase):
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store, cls.profile = _ingest(cls.label, _pack(cls.label))

    def shear_links(self) -> list[dict]:
        return [
            f.payload["link"]
            for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == "sheep_shear"
        ]


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class ShearLegacyTest(_ShearBase):
    label = "1.18.2"

    def test_sixteen_yields(self) -> None:
        links = self.shear_links()
        self.assertEqual(len(links), 16, "1.18.2 应从静态映射抽出 16 条剪毛产出")

    def test_every_link_has_shears_gate(self) -> None:
        for link in self.shear_links():
            # 节点名必须带命名空间：`bridge/tool` 产出的是 `tool:minecraft:shears`
            self.assertIn("tool:minecraft:shears", link["inputs"], f"{link['head']} 缺剪刀前置")
            self.assertIn("entity:minecraft:sheep", link["via"])

    def test_state_is_soft_not_body(self) -> None:
        """颜色与已剪毛只能是 soft。当成前置会让羊永远不可剪。"""
        for link in self.shear_links():
            self.assertTrue(any(s.startswith("flag:sheep/color=") for s in link["soft"]))
            self.assertIn("flag:sheep/unsheared", link["soft"])
            self.assertFalse(
                any(
                    n.startswith("flag:")
                    for n in (*link["via"], *link["inputs"])
                ),
                "状态约束不得进 via/inputs",
            )

    def test_count_range_from_code(self) -> None:
        # 代码是 `1 + random.nextInt(3)` → 1..3
        for link in self.shear_links():
            self.assertEqual(link["via"], ["entity:minecraft:sheep"])
        metas = [
            f.payload["meta"]
            for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == "sheep_shear"
        ]
        self.assertTrue(all(m["count"] == {"min": 1, "max": 3} for m in metas))

    def test_wool_items_are_registered(self) -> None:
        registered = set()
        for fact in self.store.of_kind("registry"):
            if fact.payload["registry"] == "minecraft:item":
                registered = set(fact.payload["entries"])
                break
        self.assertTrue(registered, "缺少物品注册表")
        for link in self.shear_links():
            self.assertIn(link["head"].split(":", 1)[1], registered)


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class ShearModernTest(_ShearBase):
    label = "26.3"

    def test_single_holds_to_real_table(self) -> None:
        links = self.shear_links()
        self.assertEqual(len(links), 1, "26.3 运行时只引用入口表，应产 1 条 holds")
        link = links[0]
        self.assertEqual(link["kind"], "holds")
        self.assertEqual(link["head"], "table:minecraft:shearing/sheep")

    def test_holds_target_exists_in_datapack(self) -> None:
        """holds 指向的表必须真实存在于数据包事实里，否则链断了。"""
        tables = {f.payload["table"] for f in self.store.of_kind("loot_table")}
        for link in self.shear_links():
            self.assertIn(link["head"].split(":", 1)[1], tables)


@unittest.skipUnless(_pack("26.3") and _pack("1.18.2"), why_all(("26.3", "1.18.2")))
class CrossVersionShearEquivalenceTest(unittest.TestCase):
    """等价性：两版最终可得的羊毛物品集合必须相同。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.legacy, _ = _ingest("1.18.2", _pack("1.18.2"))
        cls.modern, _ = _ingest("26.3", _pack("26.3"))

    def _legacy_items(self) -> set[str]:
        return {
            f.payload["link"]["head"]
            for f in self.legacy.of_kind("code_link")
            if f.payload["idiom"] == "sheep_shear"
            and f.payload["link"]["kind"] == "yield"
        }

    def _modern_items(self) -> set[str]:
        """26.3 的剪毛产出要从数据包子表读：`shearing/sheep/<color>` 的条目。"""
        out: set[str] = set()
        for fact in self.modern.of_kind("loot_table"):
            if not fact.payload["table"].startswith("minecraft:shearing/sheep/"):
                continue
            for pool in fact.payload["pools"]:
                for entry in pool["entries"]:
                    if entry.get("name"):
                        out.add(f"item:{entry['name']}")
        return out

    def test_same_item_set(self) -> None:
        legacy = self._legacy_items()
        modern = self._modern_items()
        self.assertEqual(len(legacy), 16)
        self.assertEqual(len(modern), 16)
        self.assertEqual(
            legacy,
            modern,
            f"两版剪毛产物不一致：仅 1.18.2 有 {sorted(legacy - modern)}，"
            f"仅 26.3 有 {sorted(modern - legacy)}",
        )

    def test_same_link_semantics(self) -> None:
        """一版 yield、一版 holds——链接种类不同，但都从 shear 出发。"""
        legacy_kinds = Counter(
            f.payload["link"]["kind"]
            for f in self.legacy.of_kind("code_link")
            if f.payload["idiom"] == "sheep_shear"
        )
        modern_kinds = Counter(
            f.payload["link"]["kind"]
            for f in self.modern.of_kind("code_link")
            if f.payload["idiom"] == "sheep_shear"
        )
        self.assertEqual(legacy_kinds, Counter({"yield": 16}))
        self.assertEqual(modern_kinds, Counter({"holds": 1}))


class CodeLinkShapeTest(unittest.TestCase):
    """事实形状约束：所有 code_link 都必须能进 IR。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.stores = {}
        for label in ("26.3", "1.18.2"):
            pack = _pack(label)
            if pack is not None:
                cls.stores[label] = _ingest(label, pack)[0]

    def test_every_link_matches_ir_shape(self) -> None:
        for label, store in self.stores.items():
            for fact in store.of_kind("code_link"):
                payload = fact.payload
                self.assertIn("idiom", payload)
                link = payload["link"]
                self.assertIn("head", link)
                self.assertIn("kind", link)
                self.assertIsInstance(link["via"], list)
                self.assertIsInstance(link["inputs"], list)
                self.assertIsInstance(link["soft"], list)
                self.assertIn(":", link["head"], f"{label} head 不是节点 ID：{link['head']}")

    def test_via_inputs_soft_are_disjoint(self) -> None:
        """三类条件不得重叠：中介不消耗，消耗不求存在，状态不阻塞可达。"""
        for label, store in self.stores.items():
            for fact in store.of_kind("code_link"):
                link = fact.payload["link"]
                via = set(link["via"])
                inputs = set(link["inputs"])
                soft = set(link["soft"])
                self.assertEqual(via & inputs, set(), f"{label} via/inputs 重叠")
                self.assertEqual(via & soft, set(), f"{label} via/soft 重叠")
                self.assertEqual(inputs & soft, set(), f"{label} inputs/soft 重叠")
                self.assertNotIn(
                    link["head"], via | inputs,
                    f"{label} head 不能是自己的前置：{link['head']}",
                )

    def test_kinds_are_from_the_twelve(self) -> None:
        """链接种类必须落在 12 种内。

        这条守的是阶段二的契约：IR 只认那 12 种。自造词（曾是 `place` 与
        `drops`）会让编译层需要一张翻译表，翻译表漏一项就静默丢边。
        """
        from ra.adapters.source.idioms.base import LINK_KINDS

        used: dict[str, set[str]] = {}
        for label, store in self.stores.items():
            for fact in store.of_kind("code_link"):
                kind = fact.payload["link"]["kind"]
                used.setdefault(kind, set()).add(fact.payload["idiom"])
        self.assertTrue(used, "没有任何 code_link，断言会空过")
        stray = {kind: idioms for kind, idioms in used.items() if kind not in LINK_KINDS}
        self.assertEqual(
            stray, {},
            f"这些种类不在 §4.3 词汇表内：{sorted(LINK_KINDS)}",
        )

    def test_all_heads_are_registered(self) -> None:
        """所有链接的 head 都必须是真实注册的物品，否则链是断的。"""
        for label, store in self.stores.items():
            registered = set()
            for fact in store.of_kind("registry"):
                if fact.payload["registry"] == "minecraft:item":
                    registered = set(fact.payload["entries"])
                    break
            self.assertTrue(registered, f"{label} 缺少物品注册表")
            for fact in store.of_kind("code_link"):
                head = fact.payload["link"]["head"]
                if not head.startswith("item:"):
                    continue
                self.assertIn(head.split(":", 1)[1], registered, f"{label} 未注册：{head}")


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class TradeExtractionTest(unittest.TestCase):
    """1.18.2 的交易硬编码在 VillagerTrades，需 code_link 抽取。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store, _ = _ingest("1.18.2", _pack("1.18.2"))

    def trades(self) -> list:
        return [
            f for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == "villager_trades"
        ]

    def test_produces_trades(self) -> None:
        self.assertGreater(len(self.trades()), 200, "交易抽取数量异常偏少")

    def test_all_professions_covered(self) -> None:
        """13 个职业村民 + 流浪商人。

        流浪商人不在 `VillagerProfession` 里，交易表是独立的
        `WANDERING_TRADER_TRADES`；只看职业注册表会整批漏掉它的货（附魔书、
        藏宝图都靠它或图书管理员）。
        """
        professions = {f.payload["meta"]["profession"] for f in self.trades()}
        self.assertEqual(len(professions), 14, f"职业数不符：{sorted(professions)}")
        self.assertIn("wandering_trader", professions)

    def test_levels_in_range(self) -> None:
        for fact in self.trades():
            self.assertIn(fact.payload["meta"]["level"], (1, 2, 3, 4, 5))

    def test_direction_is_not_guessed(self) -> None:
        """产出与支付必须是不同物品。"""
        for fact in self.trades():
            link = fact.payload["link"]
            self.assertNotIn("unresolved_give", fact.payload["meta"])
            head = link["head"]
            pays = [n for n in link["inputs"] if n.startswith("item:")]
            self.assertTrue(pays, f"{head} 没有支付物")
            self.assertNotIn(head, pays, f"{head} 既产出又支付，方向错了")

    def test_villager_is_assumption_not_entity(self) -> None:
        """村民用假设节点，不能挂 `entity:villager`。

        `entity:minecraft:villager` 在两个版本都零规则、状态 FALSE（结构生成
        村民这条链没有提取）。挂上去会让整批交易规则恒假：1.18.2 的附魔书、
        藏宝图因此一律不可达，而数据包形态的 26.3 却正常。
        """
        for fact in self.trades():
            link = fact.payload["link"]
            self.assertEqual(link["via"], [], f"{link['head']} 还挂着 via")
            self.assertNotIn("entity:minecraft:villager", link["inputs"])
            assumptions = [n for n in link["inputs"] if n.startswith("assume:")]
            self.assertEqual(len(assumptions), 1, f"{link['head']} 前提节点数不对")
            self.assertIn(
                assumptions[0],
                {"assume:villager_trade", "assume:wandering_trader"},
            )

    def test_multi_payment_offers_are_complete(self) -> None:
        """附魔书、藏宝图这类要两样东西的交易，两样都必须进 inputs。

        早期模型只支持一个支付物，这几类交易只能整类丢掉——附魔书在 1.18.2
        因此零规则，而它是最要紧的可交易物品之一。
        """
        by_head: dict[str, list] = {}
        for fact in self.trades():
            by_head.setdefault(fact.payload["link"]["head"], []).append(fact)

        book = by_head.get("item:minecraft:enchanted_book", [])
        self.assertTrue(book, "附魔书交易未被提取")
        self.assertIn("item:minecraft:emerald", book[0].payload["link"]["inputs"])
        self.assertIn("item:minecraft:book", book[0].payload["link"]["inputs"])

        maps = by_head.get("item:minecraft:filled_map", [])
        self.assertTrue(maps, "藏宝图交易未被提取")
        self.assertIn("item:minecraft:compass", maps[0].payload["link"]["inputs"])

    def test_coverage_is_reported_honestly(self) -> None:
        """不允许静默少抽。

        两条都算失败：

        1. 出现「未登记实参语义」——说明有交易类没补 `OFFER_SHAPES`
        2. 出现「未找到 WANDERING_TRADER_TRADES」——说明流浪商人整批漏掉
        """
        notes = [
            row.note for row in self.store.ledger.rows
            if row.rule == "idiom villager_trades 说明" and row.note
        ]
        joined = " ".join(notes)
        self.assertNotIn("未登记实参语义", joined, "有交易类没登记实参语义")
        self.assertNotIn("未找到 WANDERING_TRADER_TRADES", joined, "流浪商人交易表没找到")
        self.assertNotIn("没有能解析的条目", joined, "交易表一条都没解析出来")


class PiglinBarterTest(unittest.TestCase):
    """猪灵以物易物：金锭 → `gameplay/piglin_bartering`。

    这个机制曾经整个走目录约定挂到 `assume:player`（「钓鱼、以物易物、晨礼等
    玩家动作触发」），后果是图上黑曜石的来源标签只写「玩法掉落(piglin_bartering)」：
    看不出要付金锭，也看不出这是一次交易。付款物在代码里是写明常量，没有猜的成分。
    """

    labels = ("1.18.2", "26.3")

    def links(self, label: str) -> list[dict]:
        store, _ = _ingest(label, _pack(label))
        return [
            f.payload["link"]
            for f in store.of_kind("code_link")
            if f.payload["idiom"] == "piglin_barter"
        ]

    def test_payment_is_gold_ingot(self) -> None:
        for label in self.labels:
            with self.subTest(label=label):
                links = self.links(label)
                self.assertEqual(len(links), 1, f"{label}: 猪灵交易应恰好一条")
                self.assertEqual(
                    links[0]["head"], "table:minecraft:gameplay/piglin_bartering"
                )
                self.assertEqual(links[0]["inputs"], ["item:minecraft:gold_ingot"])

    def test_payment_is_not_optional(self) -> None:
        """金锭必须进 `inputs`，不能进 `via` 或 `soft`。

        付出去的金锭不在手里了，必须递归求可达；放进 `via` 会被当成
        「只要存在就好」，等于允许凭空以物易物。
        """
        for label in self.labels:
            with self.subTest(label=label):
                links = self.links(label)
                self.assertEqual(links[0]["soft"], [])
                self.assertEqual(links[0]["via"], [])

    def test_rule_replaces_the_directory_assumption(self) -> None:
        """代码事实优先：表不再由 `assume:player` 挂上。

        `mechanics.table_provider_rules` 的取值顺序是「事实 > 目录约定」。
        这条规则一旦生效，`gameplay` 那条目录假设就不该再作用于这个表。
        """
        from ra.ir.compile import compile_ir
        from tests import support

        for label in self.labels:
            with self.subTest(label=label):
                rules, _ = compile_ir(_ingest(label, _pack(label))[0], support.ROOT)
                bodies = [
                    sorted(rule.body)
                    for rule in rules.of_head("table:minecraft:gameplay/piglin_bartering")
                ]
                self.assertIn(
                    ["item:minecraft:gold_ingot"], bodies,
                    f"{label}: 猪灵交易表没有挂在金锭上",
                )
                self.assertNotIn(
                    ["assume:player"], bodies,
                    f"{label}: 猪灵交易仍被目录约定挂到玩家",
                )


if __name__ == "__main__":
    unittest.main()
