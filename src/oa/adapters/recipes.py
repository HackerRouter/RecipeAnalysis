"""数据包适配器：配方。

两个版本的配方 JSON 有两处方言差异，全部在语法层归一，不产生版本分支：

| 位置 | 26.3 | 1.18.2 |
|---|---|---|
| 产出 | `result: {"id": "...", "count": 2}` | `result: "minecraft:iron_ingot"` |
| 原料 | `ingredient: "minecraft:raw_iron"` | `ingredient: {"item": "minecraft:raw_iron"}` |

`type` 只记 serializer，不翻译成工艺设备——那是 IR 的知识映射。

## `crafting_special_*` 的原料槽

这一类配方的原料槽用语义名（`dye` / `fuel` / `shell` / `star` / `shapes` / `trail` /
`twinkle` …），槽名随配方不同，没有固定集合可枚举。约定是：除 `type`、`result`、
`group`、`category` 外的每个顶层键都是原料槽；值是对象时（`shapes`）其每个成员各算一个原料。
按这个通则可解析出原料，不认识的槽名报 `partial` 而不是静默留在 `extra`。

`crafting_special_repairitem` 一个槽都没有——它接受任意两件同类可修复物品，
原料集合在代码里，确实无法从数据包得出，记 `partial`。
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "recipe"

# 适配器会专门消费的字段。其余字段原样进 `extra`，不丢但也不算缺失：
# 各序列化器都有自己的专属参数（`shapes`、`material_count`、`front`…），
# 把它们的集合写死在代码里等于每版都要加一行；字段集变化交给漂移检测去报。
CONSUMED_KEYS = frozenset(
    {
        "type",
        "result",
        "results",
        "count",
        "output",
        "ingredient",
        "ingredients",
        "key",
        "pattern",
        "template",
        "base",
        "addition",
        "input",
        "material",
        "target",
        "source",
        "reagent",
        "group",
        "category",
    }
)

# `crafting_special_*` 的通则里不算原料的键：序列化器本身、产出、以及纯元信息。
SPECIAL_NON_INGREDIENT = frozenset({"type", "result", "output", "count", "group", "category"})


def parse_ingredient(node: object) -> dict | None:
    """把任意原料写法归一成 {items, tags}。

    合法写法：
    - `"minecraft:iron_ingot"`
    - `{"item": "minecraft:iron_ingot"}`
    - `{"tag": "minecraft:planks"}`
    - `[ ...以上任意 ]`（多选一）
    """
    if isinstance(node, str):
        return {"items": [node], "tags": []}
    if isinstance(node, dict):
        item = node.get("item")
        tag = node.get("tag")
        if isinstance(item, str) and not tag:
            return {"items": [item], "tags": []}
        if isinstance(tag, str) and not item:
            return {"items": [], "tags": [tag]}
        return None
    if isinstance(node, list):
        items: list[str] = []
        tags: list[str] = []
        for child in node:
            parsed = parse_ingredient(child)
            if parsed is None:
                return None
            items.extend(parsed["items"])
            tags.extend(parsed["tags"])
        return {"items": items, "tags": tags}
    return None


def parse_result(node: object) -> dict | None:
    """两种产出写法归一成 {id, count, components}。

    `{}` 是合法写法：`crafting_transmute` 用它表示「产出由输入决定」。
    这种情况记 `derived_from_input`，不能当成解析失败。
    """
    if isinstance(node, str):
        return {"id": node, "count": 1}
    if isinstance(node, dict):
        ident = node.get("id") or node.get("item")
        count = node.get("count", 1)
        out: dict = {"count": count if isinstance(count, int) else 1}
        components = node.get("components")
        if isinstance(ident, str):
            out["id"] = ident
        elif not node:
            out["derived_from_input"] = True
        else:
            return None
        if isinstance(components, dict):
            out["components"] = components
        return out
    return None


class RecipeAdapter(Adapter):
    id = "src/recipes"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        claim = profile.dirs.get("recipe")
        if claim is None:
            record(
                store,
                "data/*/recipe",
                FAMILY,
                status=LedgerStatus.FAILED,
                error="未定位配方目录",
            )
            return
        ns, _, rel = claim.path.partition("/")
        root = pack_data(pack_dir) / ns / rel
        for path in iter_json_files(root):
            self._one(path, pack_dir, store)

    def _one(self, path: Path, pack_dir: Path, store: FactStore) -> None:
        file_label = rel_posix(path, pack_dir)
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return

        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return

        serializer = doc.get("type")
        if not isinstance(serializer, str):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="缺少 type")
            return

        payload: dict = {"serializer": serializer}
        missing: list[str] = []

        # 产出：`result` 与 `output` 同义，两种写法都要认
        result_node = doc["result"] if "result" in doc else doc.get("output")
        result_key = "result" if "result" in doc else "output"
        result = None
        if result_node is not None:
            result = parse_result(result_node)
            if result is None:
                missing.append(f"{result_key} 无法解析")
            else:
                payload["result"] = result
                if result_key != "result":
                    payload["result_field"] = result_key
        if isinstance(doc.get("count"), int) and result is not None:
            result["count"] = doc["count"]

        extra: dict = {}
        for key in ("template", "base", "addition", "input", "material", "target", "source", "reagent"):
            if key in doc:
                parsed = parse_ingredient(doc[key])
                if parsed is None:
                    missing.append(f"{key} 无法解析")
                else:
                    extra[key] = parsed

        if "ingredient" in doc:
            parsed = parse_ingredient(doc["ingredient"])
            if parsed is None:
                missing.append("ingredient 无法解析")
            else:
                payload["ingredients"] = [parsed]
        if "ingredients" in doc:
            # **数组的每个元素是一个槽位**，不是一个槽位的多选。
            #
            #   "ingredients": ["minecraft:copper_block", "minecraft:honeycomb"]
            #   "ingredients": [{"item": "minecraft:copper_block"},
            #                   {"item": "minecraft:honeycomb"}]
            #
            # 两条都是「铜块 + 蜜蜡」两个槽位。整个数组交给 `parse_ingredient`
            # 会被它当成一个槽位的多选（那是给它内部 list 分支用的语义），
            # 于是上蜡铜块只需铜块或蜜蜡之一——可达性直接判错。
            #
            # 实测踩过：1.18.2 的 `waxed_copper_block` 因此从 FALSE 变 TRUE。
            # 单槽的多选写作 `"ingredients": [{"items": [A, B, C]}]`——那是
            # 数组里只有一个元素、元素内部多选，逐元素解析后仍然只有一槽。
            raw = doc["ingredients"]
            if isinstance(raw, list):
                slots_parsed: list[dict] = []
                for index, node in enumerate(raw):
                    parsed = parse_ingredient(node)
                    if parsed is None:
                        missing.append(f"ingredients[{index}] 无法解析")
                        continue
                    slots_parsed.append(parsed)
                payload["ingredients"] = slots_parsed
            else:
                parsed = parse_ingredient(raw)
                if parsed is None:
                    missing.append("ingredients 无法解析")
                else:
                    payload["ingredients"] = [parsed]

        if "key" in doc:
            key_map = doc["key"]
            if not isinstance(key_map, dict):
                missing.append("key 不是对象")
            else:
                slots: list[dict] = []
                for symbol, node in sorted(key_map.items()):
                    parsed = parse_ingredient(node)
                    if parsed is None:
                        missing.append(f"key[{symbol}] 无法解析")
                        continue
                    slots.append({"symbol": symbol, **parsed})
                payload["key"] = slots

        # `pattern` 在不同序列化器里是两种东西：合成桌里是图案行数组，
        # 锻铜纹饰里是 trim pattern 的 ID。按值的形状区分，不按序列化器名。
        if "pattern" in doc:
            pattern = doc["pattern"]
            if isinstance(pattern, str):
                payload["pattern_id"] = pattern
            elif isinstance(pattern, list) and all(isinstance(r, str) for r in pattern):
                payload["pattern"] = pattern
            else:
                missing.append("pattern 既不是字符串也不是字符串数组")

        if "results" in doc:
            results = doc["results"]
            if not isinstance(results, list):
                missing.append("results 不是数组")
            else:
                parsed_results = [parse_result(r) for r in results]
                if any(r is None for r in parsed_results):
                    missing.append("results 有无法解析的项")
                else:
                    payload["results"] = parsed_results

        for key in ("group", "category"):
            if key in doc:
                payload[key] = doc[key]

        # 特殊配方的原料槽：槽名不可枚举，按「除元信息外都是原料」的通则收。
        # 已经进过 payload / extra 的键跳过，不重复解析。
        if serializer.startswith("minecraft:crafting_special_"):
            for key, raw in doc.items():
                if key in SPECIAL_NON_INGREDIENT or key in payload or key in extra:
                    continue
                # 对象值的每个成员各算一个原料（`shapes` 是形状名 → 物品）
                slot = list(raw.values()) if isinstance(raw, dict) else raw
                parsed = parse_ingredient(slot)
                if parsed is None:
                    missing.append(f"{key} 无法解析")
                else:
                    extra[key] = parsed

        has_input = bool(payload.get("ingredients") or payload.get("key") or extra)
        has_output = bool(payload.get("result") or payload.get("results"))

        # 未被专门消费的字段原样保留。它们不是错误，是各序列化器的参数；
        # 字段集变化由漂移检测报告，不在这里逐文件报 partial。
        untouched = {k: v for k, v in doc.items() if k not in CONSUMED_KEYS and k not in extra}
        if untouched:
            extra["fields"] = untouched
        if extra:
            payload["extra"] = extra

        if not has_output and not has_input:
            # 只有 type 的配方：原料与产出在代码里，属「必须显式登记」的情形
            missing.append("JSON 内无原料与产出，逻辑在代码里")

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="recipe",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1)
