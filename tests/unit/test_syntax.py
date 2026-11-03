"""形状判定与语法归一的关键不变量。

这些用例全部来自实测踩过的坑，不是设想：
- worldgen 的 `input`/`source`/`target` 键曾被误当成配方信号
- `typed_only` 曾被算进覆盖率分母，导致配方目录虚低
- 标签空成员、`{}` 产出、字符串 `pattern` 都曾被误判为解析失败
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oa.adapters.loot import condition_type, normalize_conditions, normalize_functions, walk_entry
from oa.adapters.recipes import parse_ingredient, parse_result
from oa.probe.shapes import LOOT_TABLE, RECIPE, TAG, TYPED_ONLY, UNKNOWN, classify, resolve_dominant


class ShapeTest(unittest.TestCase):
    def test_density_function_is_not_recipe(self) -> None:
        # 实测：worldgen/density_function/*.json 含 `input`，曾被误判成配方
        self.assertEqual(classify({"type": "minecraft:cache", "input": "minecraft:a"}), TYPED_ONLY)
        self.assertEqual(
            classify({"type": "minecraft:randomized_int", "source": "minecraft:a"}), TYPED_ONLY
        )
        self.assertEqual(
            classify({"type": "minecraft:netherrack_replace_blobs", "target": "minecraft:x"}),
            TYPED_ONLY,
        )

    def test_recipe_shapes(self) -> None:
        self.assertEqual(classify({"type": "minecraft:smelting", "result": {"id": "x"}}), RECIPE)
        self.assertEqual(classify({"type": "minecraft:crafting_shapeless", "ingredients": []}), RECIPE)
        self.assertEqual(classify({"type": "minecraft:crafting_shaped", "pattern": ["#"]}), RECIPE)

    def test_tag_and_loot(self) -> None:
        self.assertEqual(classify({"values": ["minecraft:a"]}), TAG)
        self.assertEqual(classify({"values": [], "replace": True}), TAG)
        self.assertEqual(classify({"pools": []}), LOOT_TABLE)
        self.assertEqual(classify({"random_sequence": "minecraft:x"}), LOOT_TABLE)
        self.assertEqual(classify({"type": "minecraft:block"}), TYPED_ONLY)
        self.assertEqual(classify([1, 2, 3]), UNKNOWN)

    def test_typed_only_not_in_denominator(self) -> None:
        # 51 个真配方 + 9 个只有 type 的 special 配方 → 仍应是配方目录，且按 51/51 算
        shape, ratio = resolve_dominant({RECIPE: 51, TYPED_ONLY: 9})
        self.assertEqual(shape, RECIPE)
        self.assertAlmostEqual(ratio, 1.0)

    def test_noise_is_not_dominant(self) -> None:
        # 55 个未知 + 1 个含 result 的噪点 → 不能当成配方目录
        shape, _ = resolve_dominant({UNKNOWN: 55, RECIPE: 1})
        self.assertIsNone(shape)


class IngredientTest(unittest.TestCase):
    def test_all_four_writings(self) -> None:
        self.assertEqual(parse_ingredient("minecraft:iron_ingot"), {"items": ["minecraft:iron_ingot"], "tags": []})
        self.assertEqual(
            parse_ingredient({"item": "minecraft:iron_ingot"}), {"items": ["minecraft:iron_ingot"], "tags": []}
        )
        self.assertEqual(
            parse_ingredient({"tag": "minecraft:planks"}), {"items": [], "tags": ["minecraft:planks"]}
        )
        self.assertEqual(
            parse_ingredient(["minecraft:a", {"item": "minecraft:b"}]),
            {"items": ["minecraft:a", "minecraft:b"], "tags": []},
        )

    def test_unparsable(self) -> None:
        self.assertIsNone(parse_ingredient({"neither": "x"}))
        self.assertIsNone(parse_ingredient(42))


class IngredientSlotTest(unittest.TestCase):
    """`ingredients` 数组的每个元素是一个槽位，不是一个槽位的多选。

    这是实测踩过的真 bug：整个数组交给 `parse_ingredient` 会被它当成
    「一个槽内多选」，于是 `["copper_block", "honeycomb"]` 被读成
    「铜块或蜜蜡之一」，上蜡铜块只需其中任一样——可达性直接判错
    （1.18.2 的 `waxed_copper_block` 因此从 FALSE 变 TRUE）。
    """

    def _fact(self, doc: dict):
        from oa.adapters.recipes import RecipeAdapter
        from oa.facts import FactStore

        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            path = pack / "data" / "minecraft" / "recipe" / "x.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(doc), encoding="utf-8")
            store = FactStore("t")
            RecipeAdapter()._one(path, pack, store)
            facts = store.of_kind("recipe")
        self.assertEqual(len(facts), 1)
        return facts[0]

    def test_each_element_is_its_own_slot(self) -> None:
        """两件不同东西 = 两个槽（26.3 的字符串数组写法）。"""
        fact = self._fact(
            {
                "type": "minecraft:crafting_shapeless",
                "ingredients": ["minecraft:copper_block", "minecraft:honeycomb"],
                "result": {"id": "minecraft:waxed_copper_block"},
            }
        )
        slots = fact.payload["ingredients"]
        self.assertEqual(len(slots), 2, "两个元素被并成了一个槽")
        self.assertEqual(slots[0]["items"], ["minecraft:copper_block"])
        self.assertEqual(slots[1]["items"], ["minecraft:honeycomb"])

    def test_legacy_object_form_also_splits(self) -> None:
        """1.18.2 的 `[{item: A}, {item: B}]` 同样是两个槽。"""
        fact = self._fact(
            {
                "type": "minecraft:crafting_shapeless",
                "ingredients": [
                    {"item": "minecraft:copper_block"},
                    {"item": "minecraft:honeycomb"},
                ],
                "result": {"item": "minecraft:waxed_copper_block"},
            }
        )
        self.assertEqual(len(fact.payload["ingredients"]), 2)

    def test_singular_ingredient_is_one_slot_with_choices(self) -> None:
        """单槽多选用 **`ingredient`（单数）** + 数组。

        ```jsonc
        "ingredient": ["minecraft:golden_pickaxe", "minecraft:golden_shovel", …]
        ```

        熔炉只有一个输入槽，所以 12 种金装备是一个槽、12 个选项，不是 12 个槽。
        单数与复数只差一个 s，但语义完全相反：前者是 OR，后者是 AND。
        """
        fact = self._fact(
            {
                "type": "minecraft:smelting",
                "ingredient": ["minecraft:a", "minecraft:b", "minecraft:c"],
                "result": {"id": "minecraft:out"},
            }
        )
        slots = fact.payload["ingredients"]
        self.assertEqual(len(slots), 1, "单槽多选被拆成了多个槽")
        self.assertEqual(slots[0]["items"], ["minecraft:a", "minecraft:b", "minecraft:c"])

    def test_plural_ingredient_with_nested_array_is_one_slot(self) -> None:
        """复数形式里，某个元素本身是数组时，那个元素仍是一个槽。"""
        fact = self._fact(
            {
                "type": "minecraft:crafting_shapeless",
                "ingredients": [["minecraft:a", "minecraft:b"], "minecraft:c"],
                "result": {"id": "minecraft:out"},
            }
        )
        slots = fact.payload["ingredients"]
        self.assertEqual(len(slots), 2)
        self.assertEqual(slots[0]["items"], ["minecraft:a", "minecraft:b"])
        self.assertEqual(slots[1]["items"], ["minecraft:c"])


class ResultTest(unittest.TestCase):
    def test_legacy_string(self) -> None:
        self.assertEqual(parse_result("minecraft:iron_ingot"), {"id": "minecraft:iron_ingot", "count": 1})

    def test_modern_object(self) -> None:
        self.assertEqual(
            parse_result({"id": "minecraft:iron_ingot", "count": 3}),
            {"id": "minecraft:iron_ingot", "count": 3},
        )

    def test_empty_object_means_derived(self) -> None:
        # crafting_transmute 的 `result: {}` 表示产出由输入决定，是合法写法
        result = parse_result({})
        self.assertIsNotNone(result)
        self.assertTrue(result["derived_from_input"])


class SpecialSlotTest(unittest.TestCase):
    """`crafting_special_*` 的原料槽名不可枚举，按「除元信息外都是原料」收。

    踩过的坑：`firework_star` 的原料写在 `dye`/`fuel`/`shapes`/`trail`/`twinkle` 里，
    适配器只认固定槽名，于是 body 为空、规则不产、物品躲进 `no_rule`。
    """

    def _fact(self, doc: dict):
        from oa.adapters.recipes import RecipeAdapter
        from oa.facts import FactStore

        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp)
            path = pack / "data" / "minecraft" / "recipe" / "x.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(doc), encoding="utf-8")
            store = FactStore("t")
            RecipeAdapter()._one(path, pack, store)
            facts = store.of_kind("recipe")
        self.assertEqual(len(facts), 1, "一个文件必须产一条事实，不得静默跳过")
        return facts[0]

    def test_semantic_slots_are_ingredients(self) -> None:
        fact = self._fact(
            {
                "type": "minecraft:crafting_special_firework_star",
                "dye": "#minecraft:dyes",
                "fuel": "minecraft:gunpowder",
                "shapes": {"star": "minecraft:gold_nugget"},
                "group": "fireworks",
                "count": 1,
                "result": {"id": "minecraft:firework_star"},
            }
        )
        extra = fact.payload["extra"]
        self.assertEqual(extra["dye"]["items"], ["#minecraft:dyes"])
        self.assertEqual(extra["fuel"]["items"], ["minecraft:gunpowder"])
        # 对象值的成员各算一个原料
        self.assertEqual(extra["shapes"]["items"], ["minecraft:gold_nugget"])
        # 元信息不是原料槽
        self.assertNotIn("group", extra)
        self.assertNotIn("count", extra)
        self.assertEqual(fact.status.value, "parsed")

    def test_unparsable_slot_is_reported(self) -> None:
        # 不认识又解析不了的槽不能静默留在 extra 里
        fact = self._fact(
            {
                "type": "minecraft:crafting_special_x",
                "odd": 5,
                "result": {"id": "minecraft:x"},
            }
        )
        self.assertEqual(fact.status.value, "partial")
        self.assertIn("odd 无法解析", fact.missing)

    def test_no_slot_at_all_is_partial(self) -> None:
        # `crafting_special_repairitem` 真的没有任何槽：原料集合在代码里
        fact = self._fact({"type": "minecraft:crafting_special_repairitem"})
        self.assertEqual(fact.status.value, "partial")


class LootDialectTest(unittest.TestCase):
    def test_modern_condition_is_string_reference(self) -> None:
        conditions, missing = normalize_conditions({"condition": "minecraft:tool/can_silk_touch"})
        self.assertEqual(missing, [])
        self.assertEqual(conditions[0]["type"], "predicate:tool/can_silk_touch")

    def test_modern_condition_object_uses_type_key(self) -> None:
        conditions, missing = normalize_conditions({"condition": {"type": "minecraft:table_bonus"}})
        self.assertEqual(missing, [])
        self.assertEqual(conditions[0]["type"], "table_bonus")

    def test_legacy_conditions_array_uses_condition_key(self) -> None:
        conditions, missing = normalize_conditions(
            {"conditions": [{"condition": "minecraft:survives_explosion"}]}
        )
        self.assertEqual(missing, [])
        self.assertEqual(conditions[0]["type"], "survives_explosion")

    def test_modifier_object_and_array(self) -> None:
        single, missing = normalize_functions({"modifier": {"type": "minecraft:set_count", "count": 1}})
        self.assertEqual(missing, [])
        self.assertEqual(single[0]["function"], "set_count")

        many, _ = normalize_functions(
            {"modifier": [{"type": "minecraft:set_count"}, {"type": "minecraft:explosion_decay"}]}
        )
        self.assertEqual([f["function"] for f in many], ["set_count", "explosion_decay"])

    def test_legacy_functions_key(self) -> None:
        functions, _ = normalize_functions({"functions": [{"function": "minecraft:set_count"}]})
        self.assertEqual(functions[0]["function"], "set_count")

    def test_alternatives_children_flatten(self) -> None:
        rows, missing = walk_entry(
            {
                "type": "minecraft:alternatives",
                "children": [
                    {"type": "minecraft:item", "name": "minecraft:gravel"},
                    {"type": "minecraft:item", "name": "minecraft:flint"},
                ],
            }
        )
        self.assertEqual(missing, [])
        self.assertEqual([r["name"] for r in rows], [None, "minecraft:gravel", "minecraft:flint"])

    def test_unknown_entry_kind_is_reported(self) -> None:
        _, missing = walk_entry({"type": "minecraft:not_a_real_entry"})
        self.assertTrue(any("未登记的条目类型" in m for m in missing))

    def test_condition_type_helper(self) -> None:
        self.assertEqual(condition_type("minecraft:tool/can_shear"), "predicate:tool/can_shear")
        self.assertEqual(condition_type({"type": "minecraft:inverted"}), "inverted")
        self.assertIsNone(condition_type(42))


if __name__ == "__main__":
    unittest.main()
