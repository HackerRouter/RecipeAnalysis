"""代码侧的方块变换表。

同一语义在两种版本各有其道：

| 版本 | 位置 | 形状 |
|---|---|---|
| 26.3 | 数据包 `block_transformer/*.json` | `block_transform` 事实（`transformer_kind=registry`） |
| 1.18.2 | Java 静态表 | `block_transform` 事实（`transformer_kind=code_table`） |

后者是本 idiom 的职责。**两边共用同一事实种类与 payload 形状**，只有
`transformer` 的取值形态不同（注册表 ID vs `类名#字段名`）。

## 表形态（1.18.2 实测）

```java
// 直接初始化，链式 put
Map<Block, Block> STRIPPABLES =
    new ImmutableMap.Builder<Block, Block>().put(Blocks.OAK_WOOD, Blocks.STRIPPED_OAK_WOOD)....build();

// 值是 BlockState，不是 Block
Map<Block, BlockState> FLATTENABLES =
    new ImmutableMap.Builder<Block, BlockState>().put(Blocks.GRASS_BLOCK, Blocks.DIRT_PATH.defaultBlockState());

// ImmutableMap.of(...) 一次给完；value 可能嵌很深
Map<Block, Pair<Predicate<UseOnContext>, Consumer<UseOnContext>>> TILLABLES =
    Maps.newHashMap(ImmutableMap.of(Blocks.GRASS_BLOCK, Pair.of(..., HoeItem.changeIntoState(Blocks.FARMLAND...))));

// 空表 + 别处 put（内容在 static {} 或 init 里）
Map<Block, Block> POTTED_BY_CONTENT = Maps.newHashMap();
Map<Block, Block> BLOCK_BY_HOST_BLOCK = Maps.newIdentityHashMap();

// 反向表：不写字面对，声明成另一张表的 inverse
Supplier<BiMap<Block, Block>> WAX_OFF_BY_BLOCK = Suppliers.memoize(() -> WAXABLES.get().inverse());
```

前四种的取值方式都是「按出现顺序取 `Blocks.X` 常量，两两配对」——包括
`ImmutableMap.of(Blocks.A, Pair.of(..., Blocks.B))` 这种 value 嵌深的写法，常量仍成对。
反向表单独处理：方向相反，`mode` 记 `inverse`。

**不靠泛型声明正则**：`Map<Block, Pair<A, B>>` 这类三层嵌套用正则解析不可靠，
改为按语句切分后看语句里有什么。

## 不收「构造器参数推断」

原型 `transforms_source` 有一类记录形如 `src:DoorBlock(B)`，含义是「注册方块 X
时构造器参数里出现了方块常量 Y，所以 X 变成 Y」。这类不成立：
`DoorBlock(BlockSetType.OAK)` 的参数是方块族枚举，不是被转换的方块。
本 idiom 只收**显式成对声明**的表，构造器推断登记为已知缺口。

## 不判断可达性

`WeatheringCopper.NEXT_BY_BLOCK`（随机刻氧化，被动）与 `AxeItem.STRIPPABLES`
（玩家挥斧，主动）在事实层形状相同——事实只记「A 变 B」与表的位置。
「这张表由哪种手段触发」属 IR 的代理判定，事实层不做。
"""

from __future__ import annotations

import re

from ....facts import Fact, Prov
from ..index import JavaFile, JavaIndex
from ..javatext import strip_comments
from .base import Idiom, IdiomResult

ID = "block_transform_tables"

BLOCK_MAP_DECL = re.compile(r"\b(?:Map|BiMap)\s*<\s*Block\s*,")
FIELD_NAME = re.compile(r"([A-Z][A-Z0-9_]*)\s*=\s*$")
PUT_PAIR = re.compile(
    r"\.\s*put\s*\(\s*Blocks\.([A-Z][A-Z0-9_]*)\s*,\s*[^;()]*?Blocks\.([A-Z][A-Z0-9_]*)"
)
INVERSE = re.compile(r"([A-Z][A-Z0-9_]*)\s*(?:\.[a-zA-Z]+\(\))*\s*\.get\(\)\s*\.inverse\(\)")
BLOCK_CONST = re.compile(r"Blocks\.([A-Z][A-Z0-9_]*)")


def _scan_to_semicolon(text: str, start: int) -> int:
    """从 `start` 起找该语句的顶层 `;`（跳过括号与花括号内部）。

    不用「全文切 `;`」：全局深度计数一旦被未配对的括号带偏，
    后续语句会整体串位，把别的字段名当成这个声明的名字。
    实测教训：`StructureTemplate.PALETTE_TAG`（一个 String 常量）
    曾被当成方块表的字段名。
    """
    depth = 0
    i = start
    while i < len(text):
        ch = text[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                return i
        elif ch == ";" and depth <= 0:
            return i
        i += 1
    return len(text)


def _field_name(prefix: str) -> str | None:
    """取 `= ` 左侧的字段名。"""
    match = FIELD_NAME.search(prefix)
    if match is None:
        return None
    return match.group(1)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _pairs_from(fragment: str) -> tuple[list[tuple[str, str]], int]:
    """按出现顺序取 `Blocks.X` 常量并两两配对，返回 `(对列表, 常量个数)`。

    个数为奇数时不猜哪一个是多余的，返回空列表，由调用方登记。
    """
    idents = BLOCK_CONST.findall(fragment)
    if not idents or len(idents) % 2 != 0:
        return [], len(idents)
    return [(idents[i].lower(), idents[i + 1].lower()) for i in range(0, len(idents), 2)], len(idents)


class BlockTransformTables(Idiom):
    id = ID
    needs = ("静态方块变换表",)
    # 1.18.2 实测 6 张正向表、百余条成对常量；低于 50 说明解析退化。
    min_hits = 50

    def run(self, index: JavaIndex) -> IdiomResult:
        result = IdiomResult()
        tables: dict[str, dict[tuple[str, str], str]] = {}
        inverse_of: dict[str, str] = {}

        for java in index.files.values():
            text = self._relevant(java)
            if text is None:
                continue
            self._collect(java, text, tables, inverse_of, result)

        produced = 0
        for name in sorted(tables):
            for (source, target), ptr in sorted(tables[name].items()):
                self._emit(result, name, source, target, "table", ptr)
                produced += 1

        for name in sorted(inverse_of):
            other = inverse_of[name]
            pairs = tables.get(other)
            if not pairs:
                result.note(
                    f"{name}: 声明为 {other} 的反向表，但 {other} 未解析出成对常量，"
                    "反向变换未产出"
                )
                continue
            for (source, target), ptr in sorted(pairs.items()):
                self._emit(result, name, target, source, "inverse", ptr)
                produced += 1

        if produced == 0:
            result.note(
                "没有从代码里解析出任何方块变换表；"
                "该版本可能已把变换迁到数据包（如 26.x 的 block_transformer）"
            )
        return result

    # ---- 内部 ----------------------------------------------------------

    @staticmethod
    def _relevant(java: JavaFile) -> str | None:
        if "Block" not in java.text:
            return None
        if "Map<Block" not in java.text and "BiMap<Block" not in java.text:
            return None
        return strip_comments(java.text)

    def _collect(
        self,
        java: JavaFile,
        text: str,
        tables: dict[str, dict[tuple[str, str], str]],
        inverse_of: dict[str, str],
        result: IdiomResult,
    ) -> None:
        decl_at: dict[str, int] = {}

        for match in BLOCK_MAP_DECL.finditer(text):
            eq = text.find("=", match.end())
            if eq < 0:
                continue
            # 字段名取 `=` 左侧最近的标识符；`>` 与空白已由正则吃掉
            name = _field_name(text[max(0, eq - 120) : eq + 1])
            if name is None:
                continue

            end = _scan_to_semicolon(text, eq + 1)
            span = text[match.start() : end]
            decl_at.setdefault(name, match.start())

            fragment = text[eq + 1 : end]
            inverse = INVERSE.search(fragment)
            if inverse is not None:
                inverse_of.setdefault(name, inverse.group(1))
                continue
            if "Blocks." not in fragment:
                continue
            pairs, idents = _pairs_from(fragment)
            if idents and idents % 2 != 0:
                result.note(
                    f"{java.path}#{name}: 初始化式里 Blocks 常量 {idents} 个，"
                    "无法两两配对，按已知缺口登记"
                )
            for source, target in pairs:
                tables.setdefault(name, {}).setdefault(
                    (source, target),
                    f"{java.path}#{name}:L{_line_of(text, match.start())}",
                )
            _ = span  # 保留 span 便于排查，不参与判断

        if not decl_at:
            return

        # 空表形态：内容在 static {} 或方法体里的 `.put(...)`。
        # 归属取「声明位置在 put 之前且最靠后」的那张表。
        for put in PUT_PAIR.finditer(text):
            owner = self._owner_before(put.start(), decl_at)
            if owner is None or owner in inverse_of:
                continue
            source, target = put.group(1).lower(), put.group(2).lower()
            tables.setdefault(owner, {}).setdefault(
                (source, target),
                f"{java.path}#{owner}:L{_line_of(text, put.start())}",
            )

        for name in decl_at:
            if name in tables or name in inverse_of:
                continue
            if re.search(rf"\b{name}\s*\.\s*put\s*\(", text):
                # 有 put 但参数不是 `Blocks.` 字面量：内容由构造器参数驱动
                result.note(
                    f"{java.path}#{name}: 表内容由构造器参数驱动（`put(参数, this)` 形态），"
                    "非字面常量，按已知缺口登记"
                )
            else:
                result.note(f"{java.path}#{name}: 声明了方块表但全文没有填充语句")

    @staticmethod
    def _owner_before(index: int, decl_at: dict[str, int]) -> str | None:
        """`put` 调用所属的表名：声明位置在它之前且最靠后的那张。"""
        best_name: str | None = None
        best_pos = -1
        for name, pos in decl_at.items():
            if pos < index and pos > best_pos:
                best_pos = pos
                best_name = name
        return best_name

    @staticmethod
    def _emit(
        result: IdiomResult,
        table: str,
        source: str,
        target: str,
        mode: str,
        ptr: str,
    ) -> None:
        file_part, _, rest = ptr.partition("#")
        result.add_fact(
            Fact(
                kind="block_transform",
                payload={
                    "transformer": f"{file_part}#{table}",
                    "transformer_kind": "code_table",
                    "mode": mode,
                    "from": [f"block:minecraft:{source}"],
                    "to": f"block:minecraft:{target}",
                    "properties": {},
                    "soft": [],
                    "loot": None,
                    "drop_strategy": None,
                    "damage_per_use": None,
                    "disallowed_faces": [],
                    "particle": None,
                    "sound": None,
                    "update_from_neighbors": False,
                    "transform_type": None,
                },
                prov=Prov(input="src", file=file_part, ptr=rest),
            ),
            file_part,
        )


def exported() -> list[Idiom]:
    return [BlockTransformTables()]
