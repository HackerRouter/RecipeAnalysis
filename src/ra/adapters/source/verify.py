"""反编译源码事实的后验对账。

idiom 从 Java 文本推出节点名（类名小写、字段名小写、文件名去前缀），
都是**推断**。推断必须对账，否则错名字会静默变成悬空边，直到 IR 或报告阶段
才以「不可达」的形式暴露，那时已经看不出根因。

四类对账与各自的推断来源：

| 校验 | 推断来源 | 对照 |
|---|---|---|
| `verify_drop_refs` | 文件名 → 实体名 | `entity_type` 注册表 |
| `verify_fluid_bucket_blocks` | 流体 / 方块常量名 → 方块名 | `block` 注册表 |
| `verify_structure_refs` | 类名 → 结构名 | `worldgen` 事实 |
| `verify_place_refs` | 字段名 → 物品 / 方块名 | `item` 与 `block` 注册表 |
| `verify_table_refs` | 被借用方块名 → 战利品表 id | `loot_table` 事实 |

命中不了的按两种方式处理，取决于能否修正：

- **能给候选链就修正**（`via_candidates`，如 `WitherBoss` → `wither_boss` /
  `wither`），修正本身留台账
- **不能修正就剔除**事实并留台账，不让错名字进 IR

注册表或事实为空时跳过，不报错——那是上游没产出，不是这里的问题。
"""

from __future__ import annotations

from ...facts import Fact, FactStore, LedgerStatus
from ...probe.worldgen import WORLDGEN_SUBDIR_ALIASES
from ..base import record
from .common import FAMILY, JAVA_PREFIX

__all__ = [
    "known_structures",
    "verify_drop_refs",
    "verify_fluid_bucket_blocks",
    "verify_mining_refs",
    "verify_place_refs",
    "verify_structure_refs",
    "verify_table_refs",
]


def verify_mining_refs(store: FactStore) -> None:
    """`mining` 事实的方块与物品必须落在注册表全集里。

    硬度与速度都是从注册点的字面量推出来的，注册名一旦推错，数值再对也没用：
    下游拿到的是不存在的方块 id。多出来的直接剔除并留台账，缺的记失败——
    前者说明解析器认错了名字，后者说明有注册形态没覆盖到。
    """
    blocks = _registry_entries(store, "minecraft:block")
    items = _registry_entries(store, "minecraft:item")
    if not blocks or not items:
        return

    extra_blocks: set[str] = set()
    extra_items: set[str] = set()
    for fact in list(store.of_kind("mining")):
        payload = fact.payload
        if payload.get("form") == "block" and payload["block"] not in blocks:
            extra_blocks.add(payload["block"])
            store.drop(fact)
        elif payload.get("form") == "tool" and payload["item"] not in items:
            extra_items.add(payload["item"])
            store.drop(fact)

    for label, extra in (("block", extra_blocks), ("tool", extra_items)):
        if not extra:
            continue
        record(
            store,
            f"{JAVA_PREFIX}/<mining:extra-{label}>",
            FAMILY,
            status=LedgerStatus.CLASSIFIED_SKIP,
            rule=f"挖掘事实的 {label} id 不在注册表",
            note=f"{len(extra)} 条已剔除：{', '.join(sorted(extra)[:8])}",
        )

    parsed = {
        fact.payload["block"]
        for fact in store.of_kind("mining")
        if fact.payload.get("form") == "block"
    }
    missing = sorted(blocks - parsed)
    if missing:
        record(
            store,
            f"{JAVA_PREFIX}/<mining:missing-blocks>",
            FAMILY,
            status=LedgerStatus.FAILED,
            error=(
                f"{len(missing)} 个注册方块没有硬度事实，"
                f"注册形态未覆盖：{', '.join(missing[:8])}"
            ),
        )


def _registry_entries(store: FactStore, registry: str) -> set[str]:
    for fact in store.of_kind("registry"):
        if fact.payload.get("registry") == registry:
            return set(fact.payload["entries"])
    return set()


def _drop_link(store: FactStore, idiom: str) -> list[Fact]:
    return [
        fact
        for fact in list(store.of_kind("code_link"))
        if fact.payload["idiom"] == idiom
    ]


def _reject(store: FactStore, fact: Fact, node: str, why: str, rule: str) -> None:
    """剔除一条节点名不合格的事实，并留一条台账。

    同一节点可能有多条事实（如一个结构里两处放了同一物品），台账只能有一行，
    所以先看有没有记过；记过就只在 note 里累加计数。
    """
    store.drop(fact)
    key = f"{JAVA_PREFIX}/<bad-node:{node}>"
    existing = next(
        (row for row in store.ledger.rows if row.file == key and row.rule == rule),
        None,
    )
    if existing is not None:
        return
    record(
        store,
        key,
        FAMILY,
        status=LedgerStatus.CLASSIFIED_SKIP,
        rule=rule,
        note=f"{why}：{node}（来源 {fact.prov.file}）；该条事实已剔除",
    )


def verify_drop_refs(store: FactStore) -> None:
    """`drops` 链接的携带者必须在 `entity_type` 注册表里。

    实体名由文件名推出（`ZombieHorse` → `zombie_horse`），属推断，必须对账。

    带 `meta.via_candidates` 的事实给的是**候选链**（`WitherBoss` →
    `[wither_boss, wither]`，真实注册名是 `wither`），所以先按链找第一个
    命中注册表的候选并改写，链上全不命中才剔除。改写同样留台账。
    """
    entities = _registry_entries(store, "minecraft:entity_type")
    if not entities:
        return
    for fact in _drop_link(store, "drops_source") + _drop_link(store, "death_drops"):
        via = fact.payload["link"]["via"]
        if not via:
            continue
        node = via[0]
        entity = node.split(":", 1)[1] if node.startswith("entity:") else node
        if entity in entities:
            continue

        candidates = (fact.payload.get("meta") or {}).get("via_candidates") or []
        chosen = next(
            (
                candidate
                for candidate in candidates
                if candidate.startswith("entity:")
                and candidate.split(":", 1)[1] in entities
            ),
            None,
        )
        if chosen is not None:
            _rewrite_via(store, fact, chosen)
            continue

        _reject(
            store,
            fact,
            node,
            "实体不在注册表",
            "实体名由文件名推断，与注册表不符",
        )


def _rewrite_via(store: FactStore, fact: Fact, chosen: str) -> None:
    """把一条 code_link 的 `via` 改成对账命中的候选，并留台账。"""
    original = fact.payload["link"]["via"][0]
    payload = {
        **fact.payload,
        "link": {**fact.payload["link"], "via": [chosen, *fact.payload["link"]["via"][1:]]},
        "meta": {**fact.payload.get("meta", {}), "via_inferred_from": original},
    }
    store.drop(fact)
    store.add(
        Fact(kind="code_link", payload=payload, prov=fact.prov, status=fact.status)
    )
    key = f"{JAVA_PREFIX}/<node-inferred:{chosen}>"
    if any(row.file == key for row in store.ledger.rows):
        return
    record(
        store,
        key,
        FAMILY,
        status=LedgerStatus.CLASSIFIED_SKIP,
        rule="类名推断的实体名按注册表修正",
        note=f"{original} 不在注册表，改用 {chosen}（来源 {fact.prov.file}）",
    )


def known_structures(store: FactStore) -> set[str]:
    """从 `worldgen` 事实里取结构注册名（裸名，不含命名空间）。

    数据包侧子目录叫 `structure`，运行期导出侧叫 `configured_structure_feature`，
    用 probe 的同一张别名表归一。测试直接调这里，避免自己再实现一份。
    """
    found: set[str] = set()
    for fact in store.of_kind("worldgen"):
        payload = fact.payload
        # 事实里的字段名是 `worldgen_kind`，不是 `kind`（`kind` 已用于事实种类）
        kind = payload.get("worldgen_kind")
        if WORLDGEN_SUBDIR_ALIASES.get(kind, kind) != "structure":
            continue
        ident = payload.get("id")
        if isinstance(ident, str):
            # `id` 装的是相对路径（`.../bastion_remnant`），注册名是最后一段
            found.add(ident.rsplit("/", 1)[-1])
    return found


def verify_structure_refs(store: FactStore) -> None:
    """`structure:` 节点必须对应真实存在的结构。

    结构名由类名推出（`EndCityPieces` → `end_city`），属推断，必须对账。
    """
    structures = known_structures(store)
    if not structures:
        return

    for fact in _drop_link(store, "structure_gadgets"):
        via = fact.payload["link"]["via"]
        if not via:
            continue
        node = via[0]
        if not node.startswith("structure:"):
            continue
        # `structure:minecraft:end_city` → `end_city`（集合里是裸名）
        ident = node.split(":")[-1]
        if ident not in structures:
            _reject(
                store,
                fact,
                node,
                "结构不在 worldgen 事实里",
                "结构名由类名推断，与注册不符",
            )


def verify_fluid_bucket_blocks(store: FactStore) -> None:
    """流体桶里装的那个方块必须真实存在。

    常量名按小写当方块名用（`Fluids.WATER` → `block:minecraft:water`），这是推断：
    `Fluids` 里有不是方块的常量（`FLOWING_WATER`），`Blocks` 里也有名字对不上的可能。
    名字不在 block 注册表时不能留在 body 里——不存在的节点恒假，桶会静默变成
    不可达，报告只会说「不可获取」，看不出根因是常量名没对上。

    处理方式与其它对账一致：能保留的部分保留（「空桶 → 满桶」这层事实仍可靠），
    只揟下那个 `via` 并留台账，不整条剔除。
    """
    blocks = _registry_entries(store, "minecraft:block")
    if not blocks:
        return

    dropped: dict[str, str] = {}
    for fact in _drop_link(store, "fluid_buckets"):
        link = fact.payload["link"]
        via = link.get("via") or []
        kept = [node_id for node_id in via if node_id.split(":", 1)[1] in blocks]
        if len(kept) == len(via):
            continue
        for node_id in via:
            if node_id not in kept:
                dropped.setdefault(node_id, fact.prov.file)
        payload = {
            **fact.payload,
            "link": {**link, "via": kept},
            "meta": {
                **fact.payload.get("meta", {}),
                "via_dropped": [n for n in via if n not in kept],
            },
        }
        store.drop(fact)
        store.add(
            Fact(kind="code_link", payload=payload, prov=fact.prov, status=fact.status)
        )

    for node_id, file in sorted(dropped.items()):
        record(
            store,
            f"{JAVA_PREFIX}/<bad-node:{node_id}>",
            FAMILY,
            status=LedgerStatus.CLASSIFIED_SKIP,
            rule="流体桶的内容名推不出方块",
            note=(
                f"不在 block 注册表：{node_id}（来源 {file}）；"
                "只揟下该前置，桶仍由空桶成立"
            ),
        )


def verify_place_refs(store: FactStore) -> None:
    """`place` 链接两端的名字都要真实存在。

    `place` 的 `head` 是方块、`meta.item` 是物品，两者都由 Java 字段名小写推出。
    推断必须对账：名字不在注册表里就说明字段名与注册名不等（如某版改了命名），
    记 `failed` 而不是把错名字留在事实里。
    """
    items: set[str] = set()
    blocks: set[str] = set()
    for fact in store.of_kind("registry"):
        registry = fact.payload.get("registry")
        if registry == "minecraft:item":
            items = set(fact.payload["entries"])
        elif registry == "minecraft:block":
            blocks = set(fact.payload["entries"])
    if not items or not blocks:
        return

    bad: list[tuple[str, str, str]] = []
    for fact in list(store.of_kind("code_link")):
        if fact.payload["idiom"] != "place_source":
            continue
        link = fact.payload["link"]
        # 注册表 entries 里是裸名字（`stone`），事实里是带前缀的节点 ID
        item = fact.payload["meta"]["item"].split(":", 1)[1]
        block = link["head"].split(":", 1)[1]
        if item not in items:
            bad.append((fact.payload["meta"]["item"], fact.prov.file, "物品不在注册表"))
        if block not in blocks:
            bad.append((link["head"], fact.prov.file, "方块不在注册表"))

    seen: set[tuple[str, str]] = set()
    for name, file, why in bad:
        key = (name, why)
        if key in seen:
            continue
        seen.add(key)
        # 名字推错的事实直接剔除：留着会让下游拿到不存在的节点。
        # 剔除动作本身要留痕，所以记 classified_skip 而不是悄悄少一条。
        for fact in list(store.of_kind("code_link")):
            payload = fact.payload
            if payload["idiom"] != "place_source":
                continue
            if payload["meta"]["item"] == name or payload["link"]["head"] == name:
                store.drop(fact)
        record(
            store,
            f"{JAVA_PREFIX}/<bad-node:{name}>",
            FAMILY,
            status=LedgerStatus.CLASSIFIED_SKIP,
            rule="节点名由字段名推断，与注册表不符",
            note=f"{why}：{name}（字段名与注册名不一致，来源 {file}）；该条事实已剔除",
        )


def verify_table_refs(store: FactStore) -> None:
    """`code_link` 里引用的战利品表必须真实存在。

    借用类链接的 `head` 是 `table:<id>`，id 由被借用方块的名字推出
    （`blocks/<name>`）。这是**推断**，所以要在收尾时对账：表不存在就是悬空边，
    记 failed，不静默留在事实里等 IR 阶段才发现。
    """
    known = {fact.payload.get("table") for fact in store.of_kind("loot_table")}
    known.discard(None)
    missing: dict[str, list[str]] = {}
    for fact in store.of_kind("code_link"):
        head = fact.payload["link"]["head"]
        if not head.startswith("table:"):
            continue
        table_id = head[len("table:") :]
        if table_id in known:
            continue
        missing.setdefault(table_id, []).append(fact.prov.file)

    for table_id in sorted(missing):
        files = sorted(set(missing[table_id]))
        record(
            store,
            f"{JAVA_PREFIX}/<missing-table:{table_id}>",
            FAMILY,
            status=LedgerStatus.FAILED,
            error=f"引用的战利品表 {table_id} 不在 loot_table 事实里；来源 {', '.join(files[:3])}",
        )
