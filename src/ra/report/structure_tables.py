"""结构内部布局的可查表。

输入是已落盘的事实，不读 `inputs/`；输出给下游做**上界校验**：

| 表 | 一行是 | 用途 |
|---|---|---|
| `structures` | 一个拼图结构 | 允许出现的模板、权重、拼装深度上限 |
| `template_containers` | 一个容器 | 容器白名单（模板 → 坐标或处理器 + 战利品表） |
| `template_blocks` | 一个方块状态 | 结构专有方块白名单（含状态与数量）；`structure_block` 行带 `markers` |
| `structure_containers` | 一个结构类型上的容器绑定 | 没有模板的结构（神殿/要塞/矿井）在代码里的带表容器 |

只出身份与白名单，不出数量：一个结构实例里实际有几个箱子、几个方块，
取决于运行期拼装结果，数据包给不出；`structure_containers` 的 `sites` 是
调用点个数，同样的量级警告适用。

`template_containers` 的 `via` 区分容器来源：

- `template`：模板 NBT 里自带，行里给 `pos`。
- `processor`：处理器把方块换成带表的方块（可疑沙/砾石），行里给 `processor`
  与 `limit`（每片段最多几处），`pos` 为 null。

`template` 行的 `table` 可以为 null：那格容器在模板里，表由结构生成代码在运行时
挂上。这种行带 `loot_bound: "code"`，用来与「这里真的没有容器」区分。

`start_pool` 指向模板池；池内元素按 `element` 摊平，`list_pool_element` 的
嵌套成员带 `nested`。`weight_total` 是同一池内顶层元素的权重和，
嵌套元素不参与它的分母。

`template_blocks` 的 `markers` 是模板里的**数据标记名**：`structure_block{mode:data}`
方块实体上的 `metadata`。它是一类不以方块表达的机制——海军遗构的溺尸、船骸的三种箱子、
末地城的哨兵，都由结构生成代码按标记名决定。标记名不在任何战利品表里：
只看方块状态，模板里只有一堆 `structure_block{mode:data}`，看不出那里会冒出什么。

标记名挂在方块状态行上，不拆成单独的行：同一格既是一个方块也是一个标记，
拆行会让 `count` 重复计一遍。`structure_containers` 的 `markers` 是同一概念的代码侧写法
（`handleDataMarker` 的分支名），两处同形，都是名字列表。
"""

from __future__ import annotations

from ..facts import Fact, FactStore

# 产物文件名与表名一致。
TABLE_STRUCTURES = "structures"
TABLE_CONTAINERS = "template_containers"
TABLE_BLOCKS = "template_blocks"
TABLE_STRUCTURE_CONTAINERS = "structure_containers"

TABLE_NAMES = (
    TABLE_STRUCTURES,
    TABLE_CONTAINERS,
    TABLE_BLOCKS,
    TABLE_STRUCTURE_CONTAINERS,
)


def ident_of(raw: object, kind: str | None) -> str | None:
    """事实 id → 注册表标识。

    数据包形态 `data/<ns>/worldgen/<类型>/<路径>`。运行期导出的 id 是
    `<类型>/<路径>`，命名空间固定为原版。
    """
    if not isinstance(raw, str) or not raw:
        return None
    marker = "/worldgen/"
    if marker in raw:
        head, _, tail = raw.partition(marker)
        namespace = head.rsplit("/", 1)[-1]
        _, _, local = tail.partition("/")
        return f"{namespace}:{local}"
    prefix = f"{kind}/" if kind else ""
    if prefix and raw.startswith(prefix):
        local = raw[len(prefix) :]
    elif "/" in raw:
        local = raw.rsplit("/", 1)[-1]
    else:
        local = raw
    return f"minecraft:{local}" if local else None


def _local(ident: str) -> str:
    """`minecraft:village/plains/town_centers` → `village/plains/town_centers`。"""
    return ident.split(":", 1)[-1]


def _phase(value: str) -> tuple[str, str | None]:
    """`minecraft:oak_door{half:lower}` → (`minecraft:oak_door`, `half:lower`)。"""
    block, sep, rest = value.partition("{")
    if not sep:
        return value, None
    return block, rest[:-1] if rest.endswith("}") else rest


def _processor_ids(raw: object) -> list[str]:
    """池元素的 `processors`：字符串或字符串列表。内联对象不计。"""
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def _structure_rows(
    pools: dict[str, list[dict]],
    structures: dict[str, dict],
    template_pools: dict[str, tuple[str, ...]],
    processor_loot: dict[str, list[dict]],
) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    derived: list[dict] = []
    for ident, structure in sorted(structures.items()):
        visited: set[str] = set()
        pending = [structure["start_pool"]]
        pools_out: list[dict] = []
        while pending:
            pool_id = pending.pop(0)
            if pool_id in visited:
                continue
            visited.add(pool_id)
            elements = pools.get(pool_id)
            if elements is None:
                continue
            templates: list[dict] = []
            for element in elements:
                location = element.get("location")
                if not isinstance(location, str):
                    continue
                template = _local(location)
                entry = {
                    "template": template,
                    "weight": element.get("weight", 1),
                    "element_type": element.get("element_type"),
                    "nested": bool(element.get("nested")),
                }
                processors = element.get("processors")
                if processors is not None:
                    entry["processors"] = processors
                templates.append(entry)
                if location in pools and location not in visited:
                    pending.append(location)
                # 模板内拼图方块引用的池，继续向下展开
                for next_pool in template_pools.get(template, ()):
                    if next_pool not in visited:
                        pending.append(next_pool)
                # 处理器把方块换成带表的方块（可疑沙/砾石）：模板里看不到，只能从处理器定义取
                for processor in _processor_ids(processors):
                    for injection in processor_loot.get(processor, ()):
                        derived.append(
                            {
                                "template": template,
                                "pos": None,
                                "table": injection.get("loot_table"),
                                "block_entity": injection.get("output_state"),
                                "via": "processor",
                                "processor": processor,
                                "limit": injection.get("limit"),
                            }
                        )
            pools_out.append(
                {
                    "pool": pool_id,
                    "weight_total": sum(
                        element.get("weight", 1)
                        for element in elements
                        if not element.get("nested")
                    ),
                    "templates": templates,
                }
            )
        rows.append(
            {
                "structure": ident,
                "start_pool": structure["start_pool"],
                "size": structure.get("size"),
                "pools": pools_out,
            }
        )
    return rows, derived


def build_structure_tables(store: FactStore) -> dict[str, list[dict]]:
    """事实库 → `{表名: 行列表}`。四张表都按主键排序，重复运行逐字节一致。"""
    pools: dict[str, list[dict]] = {}
    structures: dict[str, dict] = {}
    processor_loot: dict[str, list[dict]] = {}
    structure_types: dict[str, str] = {}
    for fact in store.of_kind("worldgen"):
        payload = fact.payload
        kind = payload.get("worldgen_kind")
        ident = ident_of(payload.get("id"), kind)
        if ident is None:
            continue
        if kind == "template_pool":
            pools[ident] = list(payload.get("elements") or [])
        elif kind == "processor_list":
            injections = payload.get("loot_injections")
            if injections:
                processor_loot[ident] = list(injections)
        elif kind in ("structure", "configured_structure_feature"):
            structure_type = payload.get("type")
            if isinstance(structure_type, str):
                structure_types[ident] = structure_type
            start_pool = payload.get("start_pool")
            if isinstance(start_pool, str):
                structures[ident] = {
                    "start_pool": start_pool,
                    "size": payload.get("size"),
                }

    containers: list[dict] = []
    blocks: list[dict] = []
    template_pools: dict[str, tuple[str, ...]] = {}
    for fact in store.of_kind("template"):
        payload = fact.payload
        template = payload.get("template")
        if not isinstance(template, str):
            continue
        jigsaw = payload.get("jigsaw_pools")
        if jigsaw:
            template_pools[template] = tuple(sorted(set(jigsaw)))
        markers = payload.get("markers") or []
        marked = False
        for container in payload.get("containers") or []:
            table = container.get("table")
            row = {
                "template": template,
                "pos": container.get("pos"),
                "table": table,
                "block_entity": container.get("block_entity"),
                "via": "template",
            }
            if table is None:
                # 表不在模板 NBT 里，由结构生成代码在运行时挂上。行必须留：
                # 丢掉它会让这类结构看起来「一个容器都没有」，与「表看不见」混同。
                row["loot_bound"] = "code"
            containers.append(row)
        for state, count in (payload.get("block_counts") or {}).items():
            block, state_body = _phase(state)
            row = {
                "template": template,
                "block": block,
                "state": state_body,
                "count": count,
            }
            if markers and block == "minecraft:structure_block" and (state_body or "").startswith("mode:data"):
                # 标记名挂在对应的方块状态行上：一个模板里可以同时有 `drowned` 与 `chest`，
                # 拆成多行会让 `count` 重复计一遍（同一格既是一个方块也是一个标记）。
                row["markers"] = list(markers)
                marked = True
            blocks.append(row)

        if markers and not marked:
            # palette 不可读时没有方块状态行，但标记格子仍在 nbt 里。
            # 不补行会把「看不到方块」连带成「没有标记」。
            blocks.append(
                {
                    "template": template,
                    "block": "minecraft:structure_block",
                    "state": None,
                    "count": payload.get("marker_cells") or len(markers),
                    "markers": list(markers),
                }
            )

    structure_rows, derived = _structure_rows(
        pools, structures, template_pools, processor_loot
    )
    unique: dict[tuple, dict] = {}
    for row in [*containers, *derived]:
        key = (
            row["template"],
            row["table"] or "",
            row.get("via"),
            row.get("processor"),
            str(row.get("pos")),
        )
        unique[key] = row
    containers = list(unique.values())
    containers.sort(
        key=lambda row: (
            row["template"],
            row["table"] or "",
            row.get("via", ""),
            row.get("processor") or "",
            str(row.get("pos")),
        )
    )
    blocks.sort(key=lambda row: (row["template"], row["block"], row["state"] or ""))
    return {
        TABLE_STRUCTURES: structure_rows,
        TABLE_CONTAINERS: containers,
        TABLE_BLOCKS: blocks,
        TABLE_STRUCTURE_CONTAINERS: _code_container_rows(
            store.of_kind("structure_container"), structure_types
        ),
    }


def _local_name(value: str) -> str:
    """`minecraft:ocean_monument` → `ocean_monument`。两侧命名空间写法不一致时靠它对齐。"""
    return value.split(":", 1)[-1]


def _code_container_rows(
    facts: list[Fact], structure_types: dict[str, str]
) -> list[dict]:
    """代码侧容器绑定 → 一行一个（结构类型, 容器形态, 表）。

    同一绑定常在多个拼装器类里各出现一次（堡垒的桥与房间），按主键合并，
    `sites` 累加调用点个数，`sources` 记全部出处。

    `structures` 由世界生成事实的 `type` 回连（结构 JSON 的 `type` 就是这个 id），
    所以结构 id 不必从类名猜——`OceanMonumentPieces` 对应的是 `monument` 而非
    `ocean_monument`。
    """
    grouped: dict[tuple[str, str, str], dict] = {}
    for fact in facts:
        payload = fact.payload
        structure_type = payload.get("structure_type")
        container = payload.get("container")
        table = payload.get("loot_table")
        if not all(isinstance(item, str) for item in (structure_type, container, table)):
            continue
        key = (structure_type, container, table)
        row = grouped.setdefault(
            key,
            {
                "structure_type": structure_type,
                "container": container,
                "table": table,
                "sites": 0,
                "sources": set(),
            },
        )
        row["sites"] += payload.get("sites") or 1
        row["sources"].add(fact.prov.file)
        marker = payload.get("marker")
        if isinstance(marker, str):
            row.setdefault("markers", set()).add(marker)

    local_to_structures: dict[str, list[str]] = {}
    for ident, structure_type in structure_types.items():
        local_to_structures.setdefault(_local_name(structure_type), []).append(ident)

    rows: list[dict] = []
    for key in sorted(grouped):
        row = grouped[key]
        row["structures"] = sorted(
            local_to_structures.get(_local_name(row["structure_type"]), [])
        )
        row["sources"] = sorted(row["sources"])
        if "markers" in row:
            row["markers"] = sorted(row["markers"])
        rows.append(row)
    return rows
