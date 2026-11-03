"""实体自带装备（`setItemSlot` 字面量）。

判据是两条，都不靠方法名：第二个参数是 `new ItemStack(Items.X)` 字面量，
且文件不在 `world/entity/ai/` 下。`UseBonemeal` 里村民临时拿骨粉不满足这两条。
"""

from __future__ import annotations

import unittest

from oa.adapters.source.idioms.drops import LITERAL_SLOT, _entity_name


from tests.support import pack, why

class EntityNameTest(unittest.TestCase):
    def test_camel_to_snake(self) -> None:
        self.assertEqual(_entity_name(".../entity/animal/equine/ZombieHorse.java"), "zombie_horse")
        self.assertEqual(_entity_name(".../entity/monster/piglin/PiglinBrute.java"), "piglin_brute")

    def test_single_word(self) -> None:
        self.assertEqual(_entity_name(".../entity/monster/Vex.java"), "vex")

    def test_non_class_file_returns_none(self) -> None:
        self.assertIsNone(_entity_name(".../entity/package-info.java"))


class LiteralSlotTest(unittest.TestCase):
    def test_literal_is_captured(self) -> None:
        text = "this.setItemSlot(EquipmentSlot.MAINHAND, new ItemStack(Items.IRON_SPEAR));"
        match = LITERAL_SLOT.search(text)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(2), "IRON_SPEAR")

    def test_variable_assignment_is_skipped(self) -> None:
        text = "this.setItemSlot(EquipmentSlot.MAINHAND, this.item.copy());"
        self.assertIsNone(LITERAL_SLOT.search(text))

    def test_empty_stack_is_skipped(self) -> None:
        text = "this.setItemSlot(EquipmentSlot.MAINHAND, ItemStack.EMPTY);"
        self.assertIsNone(LITERAL_SLOT.search(text))


def _pack(label: str):
    return pack(label)


def _ingest(label: str, pack):
    from tests.support import store

    return store(label)


class DropIntegrationBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label, _pack(cls.label))

    def drops(self) -> list:
        return [
            f for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == "drops_source"
        ]

    def test_produces_drops(self) -> None:
        self.assertGreaterEqual(len(self.drops()), 12)

    def test_carrier_is_registered_entity(self) -> None:
        entities: set[str] = set()
        for fact in self.store.of_kind("registry"):
            if fact.payload.get("registry") == "minecraft:entity_type":
                entities = set(fact.payload["entries"])
        self.assertTrue(entities)
        for fact in self.drops():
            via = fact.payload["link"]["via"]
            self.assertEqual(len(via), 1)
            self.assertIn(via[0].split(":", 1)[1], entities, f"未知实体 {via[0]}")

    def test_no_ai_behaviour_files(self) -> None:
        """AI 行为里的临时持有不是获取途径。"""
        for fact in self.drops():
            self.assertNotIn("/entity/ai/", fact.prov.file)

    def test_abstract_base_is_reported_not_emitted(self) -> None:
        notes = [
            row.note for row in self.store.ledger.rows
            if row.rule == "idiom drops_source 说明" and row.note
        ]
        joined = "\n".join(n or "" for n in notes)
        self.assertIn("抽象类", joined, "抽象基类的装备设置没有登记")

    def test_goal_class_is_rejected(self) -> None:
        """`SkeletonTrapGoal` 在 animal/ 下但不是实体，必须被对账剔除。"""
        skips = [
            row for row in self.store.ledger.rows
            if row.rule == "实体名由文件名推断，与注册表不符"
        ]
        self.assertTrue(skips)
        self.assertTrue(any("skeleton_trap_goal" in (row.note or "") for row in skips))


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class Drop263Test(DropIntegrationBase, unittest.TestCase):
    label = "26.3"


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class Drop1182Test(DropIntegrationBase, unittest.TestCase):
    label = "1.18.2"


if __name__ == "__main__":
    unittest.main()
