"""交互表持有者的提取：类名反查、方法体工具判断、继承与接口。"""

from __future__ import annotations

import unittest
from pathlib import Path

from ra.adapters.source.idioms.interact import InteractTables
from ra.adapters.source.registry_classes import (
    Registered,
    registered_subclasses,
    registry_classes,
)
from ra.adapters.source.index import JavaFile, JavaIndex

# --- 合成的反编译源码片段（只保留判据需要的结构）---------------------------

BLOCK_ITEM_IDS = """
public class BlockItemIds {
    public static final BlockItemId BEE_NEST = BlockItemId.create("bee_nest");
    public static final BlockItemId BEEHIVE = BlockItemId.create("beehive");
    public static final BlockItemId GLOW_BERRY_CROP = BlockItemId.create("cave_vines", "glow_berries");
}
"""

BLOCKS_263 = """
public class Blocks {
    public static final Block BEE_NEST = Blocks.register(BlockItemIds.BEE_NEST, BeehiveBlock::new, BlockBehaviour.Properties.of());
    public static final Block BEEHIVE = Blocks.register(BlockItemIds.BEEHIVE, BeehiveBlock::new, BlockBehaviour.Properties.of());
    public static final Block CAVE_VINES = Blocks.register(BlockItemIds.GLOW_BERRY_CROP, CaveVinesBlock::new, BlockBehaviour.Properties.of());
}
"""

BLOCKS_1182 = """
public class Blocks {
    public static final Block BEEHIVE = Blocks.register("beehive", new BeehiveBlock(BlockBehaviour.Properties.of()));
}
"""

ENTITY_TYPE_IDS = """
public class EntityTypeIds {
    public static final ResourceKey<EntityType<?>> COW = EntityTypeIds.create("cow");
    public static final ResourceKey<EntityType<?>> MOOSHROOM = EntityTypeIds.create("mooshroom");
}
"""

ENTITY_TYPES_263 = """
public class EntityTypes {
    public static final EntityType<Cow> COW = EntityTypes.register(EntityTypeIds.COW, EntityType.Builder.of(Cow::new, MobCategory.CREATURE));
    public static final EntityType<MushroomCow> MOOSHROOM = EntityTypes.register(EntityTypeIds.MOOSHROOM, EntityType.Builder.of(MushroomCow::new, MobCategory.CREATURE));
}
"""

BUILTIN_TABLES = """
public class BuiltInLootTables {
    public static final ResourceKey<LootTable> HARVEST_BEEHIVE = BuiltInLootTables.register("harvest/beehive");
    public static final ResourceKey<LootTable> HARVEST_CAVE_VINE = BuiltInLootTables.register("harvest/cave_vine");
}
"""

BEEHIVE_BLOCK = """
public class BeehiveBlock extends BaseEntityBlock {
    public static void dropHoneycomb(ServerLevel level, ItemStack tool, BlockState state) {
        BeehiveBlock.dropFromBlockInteractLootTable(level, BuiltInLootTables.HARVEST_BEEHIVE, tool, (serverLevel, stack) -> BeehiveBlock.popResource(serverLevel, stack));
    }

    public InteractionResult use(BlockState state, Level level, BlockPos pos, Player player) {
        ItemStack itemStack = player.getItemInHand(InteractionHand.MAIN_HAND);
        if (itemStack.is(Items.SHEARS)) {
            BeehiveBlock.dropHoneycomb((ServerLevel)level, itemStack, state);
        }
        return InteractionResult.PASS;
    }
}
"""

CAVE_VINES = """
public interface CaveVines {
    public static InteractionResult use(Entity sourceEntity, BlockState state, Level level, BlockPos pos) {
        Block.dropFromBlockInteractLootTable(level, BuiltInLootTables.HARVEST_CAVE_VINE, null, sourceEntity, (serverlvl, stack) -> Block.popResource(serverlvl, pos, stack));
        return InteractionResult.SUCCESS;
    }
}
"""

CAVE_VINES_BLOCK = """
public class CaveVinesBlock extends GrowingPlantHeadBlock implements CaveVines {
}
"""

CAVE_VINES_PLANT_BLOCK = """
public class CaveVinesPlantBlock extends GrowingPlantBodyBlock implements CaveVines {
}
"""


def _index(files: dict[str, str], identifiers: dict[str, str] | None = None) -> JavaIndex:
    """合成索引：只放需要的文件，不读盘。

    `BlockItemIds` / `ItemIds` 由 `parse_constants` 从 `index.identifiers` 读
    （对应真实输入包的 `references/` 目录），所以这两个文件要同时放进那一侧。
    """
    index = JavaIndex(label="synthetic", root=Path("/nonexistent"))
    for path, text in files.items():
        index.files[path] = JavaFile(path=path, text=text, anchors=())
        if path.rsplit("/", 1)[-1] in ("BlockItemIds.java", "ItemIds.java"):
            index.identifiers[path] = text
    if identifiers:
        index.identifiers.update(identifiers)
    return index


def _base_files(**extra: str) -> dict[str, str]:
    files = {
        "net/minecraft/references/BlockItemIds.java": BLOCK_ITEM_IDS,
        "net/minecraft/world/level/block/Blocks.java": BLOCKS_263,
        "net/minecraft/world/entity/EntityTypeIds.java": ENTITY_TYPE_IDS,
        "net/minecraft/world/entity/EntityTypes.java": ENTITY_TYPES_263,
        "net/minecraft/world/level/storage/loot/BuiltInLootTables.java": BUILTIN_TABLES,
        "net/minecraft/world/level/block/BeehiveBlock.java": BEEHIVE_BLOCK,
    }
    files.update(extra)
    return files


class RegistryClassTest(unittest.TestCase):
    def test_one_class_can_have_several_names(self) -> None:
        """`BeehiveBlock` 同时注册成蜂箱与蜂巢，两条都要保留。"""
        registered = registry_classes(_index(_base_files()))
        names = [entry.name for entry in registered["BeehiveBlock"]]
        self.assertEqual(names, ["bee_nest", "beehive"])
        self.assertTrue(all(entry.kind == "block" for entry in registered["BeehiveBlock"]))

    def test_constant_gives_block_name_not_field_name(self) -> None:
        """`CAVE_VINES` 用的是 `GLOW_BERRY_CROP` 常量：方块名是 cave_vines，不是 glow_berry_crop。"""
        registered = registry_classes(_index(_base_files()))
        self.assertEqual(registered["CaveVinesBlock"], [Registered("block", "cave_vines")])

    def test_legacy_literal_form(self) -> None:
        files = {
            "net/minecraft/world/level/block/Blocks.java": BLOCKS_1182,
            "net/minecraft/world/level/block/BeehiveBlock.java": BEEHIVE_BLOCK,
        }
        registered = registry_classes(_index(files))
        self.assertEqual(registered["BeehiveBlock"], [Registered("block", "beehive")])

    def test_entity_name_is_not_camel_to_snake(self) -> None:
        """`MushroomCow` 的注册名是 mooshroom；按文件名会得到 mushroom_cow。"""
        registered = registry_classes(_index(_base_files()))
        self.assertEqual(registered["MushroomCow"], [Registered("entity", "mooshroom")])

    def test_registered_subclasses_walk_parent_chain(self) -> None:
        files = {
            "net/minecraft/world/entity/animal/cow/AbstractCow.java":
                "public abstract class AbstractCow extends Animal {\n}\n",
            "net/minecraft/world/entity/animal/cow/Cow.java":
                "public class Cow extends AbstractCow {\n}\n",
            "net/minecraft/world/entity/animal/cow/MushroomCow.java":
                "public class MushroomCow extends Cow {\n}\n",
            "net/minecraft/world/entity/animal/sheep/Sheep.java":
                "public class Sheep extends Animal {\n}\n",
        }
        registered = {
            "Cow": [Registered("entity", "cow")],
            "MushroomCow": [Registered("entity", "mooshroom")],
            "Sheep": [Registered("entity", "sheep")],
        }
        found = registered_subclasses(_index(files), registered, "AbstractCow")
        self.assertEqual(found, ["Cow", "MushroomCow"])


class InteractTableTest(unittest.TestCase):
    def _links(self, index: JavaIndex) -> list[dict]:
        return [fact.payload["link"] for fact in InteractTables().run(index).links]

    def test_static_helper_gate_comes_from_caller(self) -> None:
        """表调用封在 `dropHoneycomb` 里，剪刀判断在调用者 `use` 里。"""
        links = self._links(_index(_base_files()))
        self.assertEqual(len(links), 2, "蜂箱与蜂巢各挂一次")
        self.assertEqual(
            {link["via"][0] for link in links},
            {"block:minecraft:bee_nest", "block:minecraft:beehive"},
        )
        for link in links:
            self.assertEqual(link["head"], "table:minecraft:harvest/beehive")
            self.assertEqual(link["kind"], "holds")
            self.assertIn("tool:minecraft:shears", link["inputs"])

    def test_interface_call_lands_on_every_implementer(self) -> None:
        """`CaveVines.use` 是接口静态方法，两个实现类各是一个方块。"""
        files = {
            "net/minecraft/world/level/block/Blocks.java": BLOCKS_263,
            "net/minecraft/references/BlockItemIds.java": BLOCK_ITEM_IDS,
            "net/minecraft/world/level/storage/loot/BuiltInLootTables.java": BUILTIN_TABLES,
            "net/minecraft/world/level/block/CaveVines.java": CAVE_VINES,
            "net/minecraft/world/level/block/CaveVinesBlock.java": CAVE_VINES_BLOCK,
            "net/minecraft/world/level/block/CaveVinesPlantBlock.java": CAVE_VINES_PLANT_BLOCK,
        }
        registered = registry_classes(_index(files))
        # 合成数据里只给 CaveVinesBlock 一个注册名，所以只该产一条
        self.assertEqual(list(registered["CaveVinesBlock"])[0].name, "cave_vines")
        links = self._links(_index(files))
        self.assertEqual([link["via"][0] for link in links], ["block:minecraft:cave_vines"])
        self.assertEqual(links[0]["inputs"], [], "徒手采集不该凭空造工具前置")

    def test_unknown_class_is_reported_not_guessed(self) -> None:
        """类不在注册表、也没有已注册子类时不产事实，落 note。"""
        files = {
            "net/minecraft/world/level/storage/loot/BuiltInLootTables.java": BUILTIN_TABLES,
            "net/minecraft/world/level/block/OrphanBlock.java": BEEHIVE_BLOCK,
        }
        result = InteractTables().run(_index(files))
        self.assertEqual(result.links, [])
        self.assertTrue(any("没有已注册的子类" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
