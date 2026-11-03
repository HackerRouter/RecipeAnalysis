"""生物桶与结构代码里的物品/实体。

两者都是「数据包完全不含、只能从代码取」的获取路径，且各自踩过一个坑：

1. `mob_buckets`：注册常量是**全大写**（`EntityTypes.PUFFERFISH`），
   一律做驼峰转换会拆成 `p_u_f_f_e_r_f_i_s_h`
2. `structure_gadgets`：26.3 的构造参数外带泛型强制转换
   `(EntityType<? extends Mob>)EntityTypes.TADPOLE`，不吃掉 cast 会零命中

`elytra` 是 M2 的验收条目，它只能从这里来：不在任何战利品表、不在配方里，
模板里只有一个 `structure_block` 标记。
"""

from __future__ import annotations

import unittest

from oa.adapters.source.idioms.buckets import EMPTY_BUCKET, MOB_BUCKET, _registry_name
from oa.adapters.source.idioms.structure_gadgets import (
    ENTITY_CONST,
    ITEMSTACK,
    _branches,
    _structure_name,
)


from tests.support import pack, why

class RegistryNameTest(unittest.TestCase):
    def test_all_caps_constant_is_lowered(self) -> None:
        """`PUFFERFISH` → `pufferfish`，不是 `p_u_f_f_e_r_f_i_s_h`。"""
        self.assertEqual(_registry_name("PUFFERFISH"), "pufferfish")
        self.assertEqual(_registry_name("TROPICAL_FISH"), "tropical_fish")
        self.assertEqual(_registry_name("TADPOLE"), "tadpole")

    def test_camel_class_is_split(self) -> None:
        self.assertEqual(_registry_name("ZombieHorse"), "zombie_horse")
        self.assertEqual(_registry_name("Pig"), "pig")


class MobBucketRegexTest(unittest.TestCase):
    def test_legacy_form(self) -> None:
        text = "new MobBucketItem(EntityType.PUFFERFISH, Fluids.WATER, sound, props)"
        self.assertEqual(MOB_BUCKET.findall(text), [("PUFFERFISH", "WATER")])

    def test_modern_form_with_generic_cast(self) -> None:
        """26.3 带 `(EntityType<? extends Mob>)` 强制转换。"""
        text = (
            "new MobBucketItem((EntityType<? extends Mob>)EntityTypes.TADPOLE, "
            "Fluids.WATER, SoundEvents.X, (Item.Properties)p)"
        )
        self.assertEqual(MOB_BUCKET.findall(text), [("TADPOLE", "WATER")])

    def test_fluid_is_captured(self) -> None:
        text = "new MobBucketItem(EntityTypes.SULFUR_CUBE, Fluids.EMPTY, s, p)"
        self.assertEqual(MOB_BUCKET.findall(text), [("SULFUR_CUBE", "EMPTY")])


class StructureNameTest(unittest.TestCase):
    def test_pieces_suffix_removed(self) -> None:
        self.assertEqual(
            _structure_name("net/minecraft/world/level/levelgen/structure/structures/EndCityPieces.java"),
            "end_city",
        )

    def test_piece_suffix_removed(self) -> None:
        self.assertEqual(
            _structure_name(".../DesertPyramidPiece.java"),
            "desert_pyramid",
        )

    def test_multi_word(self) -> None:
        self.assertEqual(_structure_name(".../WoodlandMansionPieces.java"), "woodland_mansion")


class BranchTest(unittest.TestCase):
    def test_only_branch_body_is_scanned(self) -> None:
        """分支外的代码不能算进来——`chestPosition = position.below()` 就写在分支外。"""
        text = (
            "protected void handleDataMarker(String markerId, ...) {\n"
            "  BlockPos chestPosition = position.below();\n"
            "  if (markerId.startsWith(\"Chest\")) {\n"
            "    setBlock(chestPosition, Blocks.CHEST);\n"
            "  } else if (markerId.startsWith(\"Elytra\")) {\n"
            "    frame.setItem(new ItemStack(Items.ELYTRA), false);\n"
            "  }\n"
            "}\n"
        )
        branches = dict(_branches(text))
        self.assertEqual(ITEMSTACK.findall(branches["Chest"]), [])
        self.assertEqual(ITEMSTACK.findall(branches["Elytra"]), ["ELYTRA"])


def _pack(label: str):
    return pack(label)


def _ingest(label: str):
    from tests.support import store

    return store(label)


class CodePathBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label)

    def links(self, idiom: str, kind: str | None = None) -> list:
        return [
            f for f in self.store.of_kind("code_link")
            if f.payload["idiom"] == idiom
            and (kind is None or f.payload["link"]["kind"] == kind)
        ]

    def test_elytra_is_held_by_end_city(self) -> None:
        """M2 验收：`elytra` 可达（holds）。"""
        found = [
            f for f in self.links("structure_gadgets", "holds")
            if f.payload["link"]["head"] == "item:minecraft:elytra"
        ]
        self.assertEqual(len(found), 1, "elytra 应有且仅有一条 holds")
        self.assertEqual(found[0].payload["link"]["via"], ["structure:minecraft:end_city"])

    def test_shulker_spawns_in_end_city(self) -> None:
        found = [
            f for f in self.links("structure_gadgets", "spawns")
            if f.payload["link"]["head"] == "entity:minecraft:shulker"
        ]
        self.assertEqual(len(found), 1)

    def test_structure_node_is_registered(self) -> None:
        """结构名由类名推断，必须对得上 worldgen 事实。

        直接复用生产代码的取集合函数：测试自己再实现一份，两版子目录名不同时
        会分叉（`structure` vs `configured_structure_feature`），这次就是这么踩的。
        """
        from oa.adapters.source import known_structures

        known = known_structures(self.store)
        self.assertTrue(known, "worldgen 事实里没有结构，对账会空过")
        for fact in self.links("structure_gadgets"):
            node = fact.payload["link"]["via"][0]
            self.assertIn(node.split(":")[-1], known, node)

    def test_bucket_entity_names_are_valid(self) -> None:
        """桶承载的实体必须在 entity_type 注册表里。

        这条同时抓「逐字母拆开」的 bug：`PUFFERFISH` 若被驼峰转换会得到
        `p_u_f_f_e_r_f_i_s_h`，它不在注册表里，直接失败。
        """
        entities: set[str] = set()
        for fact in self.store.of_kind("registry"):
            if fact.payload.get("registry") == "minecraft:entity_type":
                entities = set(fact.payload["entries"])
        self.assertTrue(entities)
        for fact in self.links("mob_buckets"):
            entity = fact.payload["link"]["via"][0].split(":", 1)[1]
            self.assertIn(entity, entities, f"实体名不对：{entity}")

    def test_bucket_inputs_are_water_buckets(self) -> None:
        for fact in self.links("mob_buckets"):
            link = fact.payload["link"]
            if link["head"] == "item:minecraft:sulfur_cube_bucket":
                self.assertEqual(link["inputs"], [], "EMPTY 流体不产 inputs")
                continue
            self.assertEqual(link["inputs"], ["item:minecraft:water_bucket"])

    def test_no_failed_rows(self) -> None:
        self.assertEqual(self.store.ledger.failed(), [])


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class CodePath263Test(CodePathBase, unittest.TestCase):
    label = "26.3"

    def test_bucket_count(self) -> None:
        """26.3 有 7 种（含水生的五种 + 蝌蚪 + 硫磺方块）。"""
        self.assertEqual(len(self.links("mob_buckets")), 7)

    def test_tadpole_is_present(self) -> None:
        heads = {f.payload["link"]["head"] for f in self.links("mob_buckets")}
        self.assertIn("item:minecraft:tadpole_bucket", heads)


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class CodePath1182Test(CodePathBase, unittest.TestCase):
    label = "1.18.2"

    def test_bucket_count(self) -> None:
        """1.18.2 只有 5 种——蝌蚪与硫磺方块那个版本还不存在。"""
        self.assertEqual(len(self.links("mob_buckets")), 5)

    def test_tadpole_is_absent_in_this_version(self) -> None:
        heads = {f.payload["link"]["head"] for f in self.links("mob_buckets")}
        self.assertNotIn("item:minecraft:tadpole_bucket", heads)


if __name__ == "__main__":
    unittest.main()
