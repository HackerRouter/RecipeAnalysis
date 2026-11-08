"""结构内部布局的三张可查表。

输入是已落盘的事实，不读 `inputs/`；输出给下游做**上界校验**：

| 表 | 一行是 | 用途 |
|---|---|---|
| `structures` | 一个拼图结构 | 允许出现的模板、权重、拼装深度上限 |
| `template_containers` | 一个容器方块实体 | 容器白名单（模板 → 坐标 + 战利品表） |
| `template_blocks` | 一个方块状态 | 结构专有方块白名单（含状态与数量） |

只出身份与白名单，不出数量：一个结构实例里实际有几个箱子、几个方块，
取决于运行期拼装结果，数据包给不出。

`start_pool` 指向模板池；池内元素按 `element` 摊平，`list_pool_element` 的
嵌套成员带 `nested`。`weight_total` 是同一池内顶层元素的权重和，
嵌套元素不参与它的分母。
"""

from __future__ import annotations

from ..facts import FactStore

# 产物文件名与表名一致。
TABLE_STRUCTURES = "structures"
TABLE_CONTAINERS = "template_containers"
TABLE_BLOCKS = "template_blocks"

TABLE_NAMES = (TABLE_STRUCTURES, TABLE_CONTAINERS, TABLE_BLOCKS)


def _ident(raw: object, kind: str | None) -> str | None:
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


def _structure_rows(
    pools: dict[str, list[dict]],
    structures: dict[str, dict],
    template_pools: dict[str, tuple[str, ...]],
) -> list[dict]:
    rows: list[dict] = []
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
                templates.append(
                    {
                        "template": template,
                        "weight": element.get("weight", 1),
                        "element_type": element.get("element_type"),
                        "nested": bool(element.get("nested")),
                    }
                )
                if location in pools and location not in visited:
                    pending.append(location)
                # 模板内拼图方块引用的池，继续向下展开
                for next_pool in template_pools.get(template, ()):
                    if next_pool not in visited:
                        pending.append(next_pool)
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
    return rows


def build_structure_tables(store: FactStore) -> dict[str, list[dict]]:
    """事实库 → `{表名: 行列表}`。三张表都按主键排序，重复运行逐字节一致。"""
    pools: dict[str, list[dict]] = {}
    structures: dict[str, dict] = {}
    for fact in store.of_kind("worldgen"):
        payload = fact.payload
        kind = payload.get("worldgen_kind")
        ident = _ident(payload.get("id"), kind)
        if ident is None:
            continue
        if kind == "template_pool":
            pools[ident] = list(payload.get("elements") or [])
        elif kind in ("structure", "configured_structure_feature"):
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
        for container in payload.get("loot_tables") or []:
            table = container.get("table")
            if not isinstance(table, str):
                continue
            containers.append(
                {
                    "template": template,
                    "pos": container.get("pos"),
                    "table": table,
                    "block_entity": container.get("block_entity"),
                }
            )
        for state, count in (payload.get("block_counts") or {}).items():
            block, state_body = _phase(state)
            blocks.append(
                {
                    "template": template,
                    "block": block,
                    "state": state_body,
                    "count": count,
                }
            )

    containers.sort(key=lambda row: (row["template"], row["table"], str(row["pos"])))
    blocks.sort(key=lambda row: (row["template"], row["block"], row["state"] or ""))
    return {
        TABLE_STRUCTURES: _structure_rows(pools, structures, template_pools),
        TABLE_CONTAINERS: containers,
        TABLE_BLOCKS: blocks,
    }
