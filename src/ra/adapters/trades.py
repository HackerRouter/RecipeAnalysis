"""数据包适配器：村民交易。

三层结构，形状判定已由 probe 完成（不靠目录名）：

| 层 | 形状 | 内容 | 实测 26.3 |
|---|---|---|---|
| 单条交易 | `{gives, wants, max_uses, ...}` | 给什么、要什么 | `villager_trade/*` 391 |
| 交易组 | `{amount, trades: "#tag"}` | 职业+等级 → 交易标签 | `trade_set/*` 68 |
| 交易标签 | `{values: [...]}` | 把单条交易聚成组 | `tags/villager_trade/*` 73 |

标签层由 tags 适配器处理（`minecraft:villager_trade` 已在 `tag_dirs` 里）；
这里只产出前两层，`layer` 字段区分。

`wants` 与 `gives` 的写法与配方产出同构（`{id, count, components}`），
但**语义不同**：`wants` 是支付、`gives` 是所得。这一层区分留给 IR，
事实层只如实记录两边各是什么。

`wants` 一律是数组（与 `additional_wants` 同形）。附魔书这类报价在数据里写
`count = 0`，真实价格由 `enchant_randomly` 的附魔等级决定；这类报价把
`count` 写成 `{min, max}` 区间，并附 `price_model` 说明公式与等级来源。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..mcshared.trades import level as _level
from ..mcshared.trades import parse_item_stack, segment as _segment, trade_id as _trade_id
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, data_root, iter_json_files, record, rel_posix

FAMILY = "trade"

LAYER_OFFER = "offer"
LAYER_SET = "set"

__all__ = ["TradeAdapter", "parse_item_stack"]

# 标签嵌套深度上限。实测两层（`armorer/level_1` → `common_smith/level_1` → 条目），
# 给宽裕一点防环，但必须有上限。
MAX_TAG_DEPTH = 8

# 交易字段的缺省值，取自 `VillagerTrade.CODEC` 的 `optionalFieldOf`：
# `max_uses` 默认 4、`xp` 默认 1、`reputation_discount` 默认 0.0。
# 不补的话，下游读到「没有经验值」会把默认 1 当成 0——两者差一整档。
TRADE_DEFAULTS: dict[str, object] = {
    "max_uses": 4,
    "xp": 1,
    "reputation_discount": 0.0,
}


def _expand_tag(
    tags: dict[str, list[str]], tag_id: str, depth: int = 0
) -> list[str]:
    """递归展开标签里的 `#` 引用，返回条目 id 列表。"""
    if depth > MAX_TAG_DEPTH:
        return []
    out: list[str] = []
    for value in tags.get(tag_id, []):
        if value.startswith("#"):
            out.extend(_expand_tag(tags, value[1:], depth + 1))
        else:
            out.append(value)
    return out


# ---- 附魔书的对价 -------------------------------------------------------
#
# 图书管理员的附魔书报价在数据里写 `wants.count = 0`：真实价格由
# `enchant_randomly` 的附魔等级决定，公式在代码里，两版一致：
#
#   EnchantRandomlyFunction#enchantItem
#     ADDITIONAL_TRADE_COST = 2 + random.nextInt(5 + level * 10) + 3 * level
#   VillagerTrade#getOffer
#     把它加到 `wants.count` 上，再按 `TradeCost.toItemCost` 夹到
#     `[0, 物品的 max_stack_size]`
#   1.18.2 的 `EnchantBookForEmeralds#getOffer` 另有「宝藏附魔 ×2，再夹到 64」
#
# 等级区间从 `options` 指向的附魔标签展开，`max_level` 读附魔定义；
# 是否翻倍看这些附魔与 `#minecraft:double_trade_price` 的交集。

ENCHANT_RANDOMLY = frozenset({"enchant_randomly", "minecraft:enchant_randomly"})
DOUBLE_PRICE_TAG = "minecraft:double_trade_price"
DEFAULT_STACK = 64


def _enchant_tag_members(store: FactStore, tag_id: str, depth: int = 0) -> set[str]:
    """附魔标签的成员（递归展开 `nested`）。标签没有事实时返回空集。"""
    if depth > MAX_TAG_DEPTH:
        return set()
    for fact in store.of_kind("tag"):
        payload = fact.payload
        if payload.get("registry") != "minecraft:enchantment":
            continue
        if payload.get("tag") != tag_id:
            continue
        members = {
            value
            for value in payload.get("values") or ()
            if isinstance(value, str) and not value.startswith("#")
        }
        for nested in payload.get("nested") or ():
            if isinstance(nested, str):
                members |= _enchant_tag_members(store, nested, depth + 1)
        return members
    return set()


def _enchant_options(options: object, store: FactStore) -> set[str] | None:
    if isinstance(options, str) and options.startswith("#"):
        return _enchant_tag_members(store, options[1:]) or None
    if isinstance(options, list):
        members = {value for value in options if isinstance(value, str)}
        return members or None
    return None


def _enchant_levels(
    members: set[str], data_base: Path
) -> tuple[int, int] | None:
    """允许的附魔等级区间。任何一项定义缺失就返回 None，不猜。"""
    low: int | None = None
    high: int | None = None
    for ident in members:
        namespace, _, name = ident.partition(":")
        path = Path(data_base) / "data" / namespace / "enchantment" / f"{name}.json"
        if not path.is_file():
            return None
        try:
            doc = read_json(path)
        except (OSError, ValueError):
            return None
        if not isinstance(doc, dict):
            return None
        level_low = doc.get("min_level", 1)
        level_high = doc.get("max_level", 1)
        if not isinstance(level_low, int) or not isinstance(level_high, int):
            return None
        low = level_low if low is None else min(low, level_low)
        high = level_high if high is None else max(high, level_high)
    if low is None or high is None:
        return None
    return low, high


def _stack_cap(store: FactStore, item_id: str) -> int:
    """支付物的堆叠上限。组件事实缺这一项就是默认 64。"""
    for fact in store.of_kind("components"):
        if fact.payload.get("item") != item_id:
            continue
        value = (fact.payload.get("components") or {}).get("minecraft:max_stack_size")
        return value if isinstance(value, int) else DEFAULT_STACK
    return DEFAULT_STACK


def _additional_cost(level: int, doubled: bool) -> tuple[int, int]:
    """某一等级下的加价区间：`2 + rand(5+10L) + 3L`，`random` 的上界开区间。"""
    base = 2 + 3 * level
    return (base * 2, (base + 5 + 10 * level - 1) * 2) if doubled else (
        base,
        base + 5 + 10 * level - 1,
    )


def _conditional_price(
    wants: dict,
    doc: dict,
    store: FactStore,
    data_base: Path,
) -> tuple[dict, dict | None, list[str]]:
    """把「0 价 + 附魔加价」的报价换成区间，并附上价格模型。

    数据里写了 0 只是占位；不换的话下游只能判「对价不完整」并放弃这条报价。
    """
    modifiers = doc.get("given_item_modifier")
    if not isinstance(modifiers, list):
        return wants, None, []
    enchant = next(
        (
            modifier
            for modifier in modifiers
            if isinstance(modifier, dict)
            and modifier.get("type") in ENCHANT_RANDOMLY
            and modifier.get("include_additional_cost_component") is True
        ),
        None,
    )
    if enchant is None or wants.get("count") != 0:
        return wants, None, []

    members = _enchant_options(enchant.get("options"), store)
    if not members:
        return wants, None, ["price_range 无法确定：附魔选项标签没有成员"]
    levels = _enchant_levels(members, data_base)
    if levels is None:
        return wants, None, ["price_range 无法确定：附魔定义的 max_level 不可得"]

    doubled = _enchant_tag_members(store, DOUBLE_PRICE_TAG)
    overlap = members & doubled if doubled else set()
    any_doubled = bool(overlap)
    all_doubled = bool(overlap) and overlap == members

    low_level, high_level = levels
    lowest = min(
        _additional_cost(level, all_doubled)[0]
        for level in range(low_level, high_level + 1)
    )
    highest = max(
        _additional_cost(level, any_doubled)[1]
        for level in range(low_level, high_level + 1)
    )
    cap = _stack_cap(store, wants["id"])
    low = min(cap, lowest)
    high = min(cap, highest)

    priced = dict(wants)
    priced["count"] = {"min": low, "max": high}
    model = {
        "kind": "enchant_randomly",
        "formula": "2 + random(5 + 10*level) + 3*level",
        "levels": {"min": low_level, "max": high_level},
        "doubled_by": DOUBLE_PRICE_TAG,
        "doubling": "all" if all_doubled else ("some" if any_doubled else "none"),
        "clamp": cap,
        "basis": (
            "EnchantRandomlyFunction#enchantItem 写 ADDITIONAL_TRADE_COST；"
            "VillagerTrade#getOffer 加到 wants 上并按堆叠上限夹取"
        ),
    }
    return priced, model, []



class TradeAdapter(Adapter):
    id = "src/trades"

    def run(self, profile: Profile, pack_dir: Path, store: FactStore) -> None:
        missing_layers = [
            registry
            for registry, _ in (
                ("villager_trade", LAYER_OFFER),
                ("trade_set", LAYER_SET),
            )
            if profile.dirs.get(registry) is None
        ]
        if missing_layers:
            store.mark_unavailable(
                FAMILY,
                f"该版本数据包内无 {', '.join(missing_layers)}",
                "交易表可能硬编码在代码侧（如 1.18.2 的 VillagerTrades），"
                "需 code_link 族补录，否则交易路径不可达",
            )

        # 交易组目录名 = 职业全集。`villager_trade/<段>` 的首段不在这里时，
        # 那个目录是**共用条目**（`smith/` 被盔甲匠/工具匠/武器匠通过
        # `common_smith` 标签共用），不是职业。
        professions = self._subdirectories(profile, pack_dir, "trade_set")
        tags = self._trade_tags(profile, pack_dir)
        shared_groups = self._shared_groups(tags, professions)
        owners = self._trade_owners(profile, pack_dir, tags)

        reachable: set[str] = set()
        for registry, layer in (
            ("villager_trade", LAYER_OFFER),
            ("trade_set", LAYER_SET),
        ):
            claim = profile.dirs.get(registry)
            if claim is None:
                continue
            ns, _, rel = claim.path.partition("/")
            root = data_root(profile, pack_dir) / ns / rel
            if not root.is_dir():
                record(
                    store,
                    claim.path,
                    FAMILY,
                    status=LedgerStatus.FAILED,
                    error="探测给出的交易目录不存在",
                )
                continue
            for path in iter_json_files(root):
                if layer == LAYER_OFFER:
                    ident = self._offer(
                        path, data_root(profile, pack_dir).parent, ns, store, professions, shared_groups, owners
                    )
                    if ident is not None:
                        reachable.add(ident)
                else:
                    self._set(path, data_root(profile, pack_dir).parent, ns, store)

        # 没被任何 trade_set 引用的条目要留痕：可能是流浪商人那种分组命名不同的
        # 正常情况，也可能是数据包结构变了导致整批交易成了孤儿。
        orphans = sorted(ident for ident in reachable if ident not in owners)
        if orphans:
            prefixes = Counter(ident.split(":", 1)[-1].split("/", 1)[0] for ident in orphans)
            record(
                store,
                "data/*/villager_trade",
                FAMILY,
                status=LedgerStatus.CLASSIFIED_SKIP,
                rule="交易条目未被任何 trade_set 引用",
                note=(
                    f"{len(orphans)} 条；按顶层目录："
                    + "、".join(f"{name} {count}" for name, count in sorted(prefixes.items()))
                ),
            )

    def _subdirectories(
        self, profile: Profile, pack_dir: Path, registry: str
    ) -> set[str]:
        claim = profile.dirs.get(registry)
        if claim is None:
            return set()
        ns, _, rel = claim.path.partition("/")
        root = data_root(profile, pack_dir) / ns / rel
        if not root.is_dir():
            return set()
        return {path.name for path in root.iterdir() if path.is_dir()}

    def _trade_tags(self, profile: Profile, pack_dir: Path) -> dict[str, list[str]]:
        """`标签 id → values`。交易组与共用条目都靠它连起来。

        `tag_dirs` 的键带命名空间（`minecraft:villager_trade`），
        不带命名空间的写法留给旧探测结果。
        """
        claim = profile.tag_dirs.get("minecraft:villager_trade") or profile.tag_dirs.get(
            "villager_trade"
        )
        if claim is None:
            return {}
        ns, _, rel = claim.path.partition("/")
        root = data_root(profile, pack_dir) / ns / rel
        if not root.is_dir():
            return {}

        tags: dict[str, list[str]] = {}
        for path in sorted(root.rglob("*.json")):
            local = rel_posix(path, root)
            if local.endswith(".json"):
                local = local[: -len(".json")]
            try:
                doc = read_json(path)
            except (OSError, ValueError):
                continue
            values = doc.get("values")
            tags[f"minecraft:{local}"] = [
                value for value in (values or []) if isinstance(value, str)
            ]
        return tags

    def _shared_groups(
        self, tags: dict[str, list[str]], professions: set[str]
    ) -> dict[str, str]:
        """`条目目录首段 → 标签分组名`，例如 `smith → common_smith`。

        共用条目自己没有职业，它的标签被几个职业的标签嵌套引用。
        分组名从标签目录读，不按「`common_` + 首段」拼：目录名与标签名
        不会总是一致，拼出来的名字一旦错，下游会多出一个不存在的分组。

        只认**不是职业**的标签组：职业组的 values 里也有别的职业的条目首段，
        混进来会把 `toolsmith` 的条目误标成 `armorer` 的分组。
        """
        groups: dict[str, str] = {}
        for tag_id, values in tags.items():
            local = tag_id.split(":", 1)[-1]
            group = local.split("/", 1)[0]
            if group in professions:
                continue
            for value in values:
                if value.startswith("#"):
                    continue
                segment = value.split(":", 1)[-1].split("/", 1)[0]
                groups.setdefault(segment, group)
        return groups

    def _trade_owners(
        self,
        profile: Profile,
        pack_dir: Path,
        tags: dict[str, list[str]],
    ) -> dict[str, list[dict]]:
        """`条目 id → [{profession, level}]`，从交易组正向展开。

        归属由**引用方向**决定：`trade_set/<职业>/level_N` → 它的 `trades` 标签
        → 嵌套标签 → 条目。共用条目因此能解析回具体职业，不靠目录名猜。

        不按 `level_` 命名的交易组（流浪商人的 `buying` / `common` / `uncommon`）
        也照收，`level` 记 null。
        """
        claim = profile.dirs.get("trade_set")
        if claim is None:
            return {}
        ns, _, rel = claim.path.partition("/")
        root = data_root(profile, pack_dir) / ns / rel
        if not root.is_dir():
            return {}

        owners: dict[str, list[dict]] = {}
        for path in iter_json_files(root):
            try:
                doc = read_json(path)
            except (OSError, ValueError):
                continue
            trades = doc.get("trades")
            if not isinstance(trades, str) or not trades.startswith("#"):
                continue

            local = rel_posix(path, root)
            if local.endswith(".json"):
                local = local[: -len(".json")]
            parts = local.split("/")
            if not parts:
                continue
            profession = parts[0]
            level = None
            if len(parts) > 1 and parts[-1].startswith("level_"):
                try:
                    level = int(parts[-1][len("level_") :])
                except ValueError:
                    level = None

            for entry in _expand_tag(tags, trades[1:]):
                bucket = owners.setdefault(entry, [])
                owner = {"profession": profession, "level": level}
                if owner not in bucket:
                    bucket.append(owner)
        return owners

    # ---- 单条交易 ------------------------------------------------------

    def _offer(
        self,
        path: Path,
        pack_dir: Path,
        namespace: str,
        store: FactStore,
        professions: set[str],
        shared_groups: dict[str, str],
        owners: dict[str, list[dict]],
    ) -> str | None:
        file_label = rel_posix(path, pack_dir)
        doc = self._load(path, file_label, store)
        if doc is None:
            return None

        missing: list[str] = []
        gives = parse_item_stack(doc.get("gives"))
        wants = parse_item_stack(doc.get("wants"))
        if gives is None:
            missing.append("gives 无法解析")
        if wants is None:
            missing.append("wants 无法解析")

        price_model: dict | None = None
        if wants is not None:
            wants, price_model, price_missing = _conditional_price(
                wants, doc, store, pack_dir
            )
            missing.extend(price_missing)

        additional: list[dict] = []
        raw_additional = doc.get("additional_wants")
        if raw_additional is not None:
            if isinstance(raw_additional, list):
                for index, node in enumerate(raw_additional):
                    parsed = parse_item_stack(node)
                    if parsed is None:
                        missing.append(f"additional_wants[{index}] 无法解析")
                    else:
                        additional.append(parsed)
            else:
                parsed = parse_item_stack(raw_additional)
                if parsed is None:
                    missing.append("additional_wants 无法解析")
                else:
                    additional.append(parsed)

        # 首段是职业就记职业；不是职业的目录是共用条目，记共享分组。
        # 共用条目的前提仍是村民交易，所以 IR 侧仍挂 `assume:villager_trade`。
        segment = _segment(file_label, "villager_trade", 0)
        shared = segment not in professions
        payload = {
            "layer": LAYER_OFFER,
            "trade": _trade_id(file_label, "villager_trade", namespace),
            "profession": None if shared else segment,
            "level": _level(file_label, "villager_trade"),
            "gives": gives,
            "wants": [wants] if wants is not None else [],
            "additional_wants": additional,
        }
        if price_model is not None:
            payload["price_model"] = price_model
        if shared:
            payload["shared_group"] = shared_groups.get(segment, segment)
            # 共用条目的真实归属从交易组正向展开得到：一条可能同时属于
            # 几个职业（smith 的三条被盔甲匠/工具匠/武器匠共用）。
            applies = owners.get(payload["trade"])
            if applies:
                payload["applies_to"] = applies

        # 不参与获取路径判定、但下游难度可能要的字段，原样透传；
        # 数据里没写的按 codec 默认值补上，并记进 `defaults` 以便区分
        # 「显式写了 1」与「缺省得到 1」。
        meta: dict = {
            key: doc[key]
            for key in ("max_uses", "reputation_discount", "xp", "price_multiplier")
            if key in doc
        }
        defaults = [key for key in TRADE_DEFAULTS if key not in meta]
        for key in defaults:
            meta[key] = TRADE_DEFAULTS[key]
        if defaults:
            meta["defaults"] = defaults
        payload["meta"] = meta

        # 写成 node 的先例：这些键必然影响「能不能换」或「换出什么」，不可忽略
        conditional = {}
        for key in ("given_item_modifier", "merchant_predicate", "double_trade_price_enchantments"):
            if key in doc:
                conditional[key] = doc[key]
        if conditional:
            payload["conditional"] = conditional

        unknown = set(doc) - {
            "gives",
            "wants",
            "additional_wants",
            "max_uses",
            "reputation_discount",
            "xp",
            "price_multiplier",
            "given_item_modifier",
            "merchant_predicate",
            "double_trade_price_enchantments",
        }
        if unknown:
            missing.append(f"未知字段 {', '.join(sorted(unknown))}")

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="trade",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, missing=tuple(missing))
        return payload["trade"]

    # ---- 交易组 --------------------------------------------------------

    def _set(self, path: Path, pack_dir: Path, namespace: str, store: FactStore) -> None:
        file_label = rel_posix(path, pack_dir)
        doc = self._load(path, file_label, store)
        if doc is None:
            return

        missing: list[str] = []
        trades = doc.get("trades")
        if isinstance(trades, str):
            ref = trades
        elif isinstance(trades, list):
            # 少数写法直接内联交易列表
            ref = None
            missing.append("trades 内联为数组，未引用标签")
        else:
            ref = None
            missing.append("trades 既不是字符串也不是数组")

        amount = doc.get("amount")
        if not isinstance(amount, int):
            missing.append("amount 不是整数")

        level = _level(file_label, "trade_set")
        if level is None:
            # 流浪商人的交易组不按等级划分。缺这一项不影响引用关系，
            # 但下游按（职业, 等级）索引时会落空，必须显式说出来。
            missing.append("level 无法确定：该交易组不按等级划分")

        payload = {
            "layer": LAYER_SET,
            "set": _trade_id(file_label, "trade_set", namespace),
            "profession": _segment(file_label, "trade_set", 0),
            "level": level,
            "trades_ref": ref,
            "amount": amount if isinstance(amount, int) else None,
            "random_sequence": doc.get("random_sequence"),
        }

        if isinstance(trades, list):
            parsed = [parse_item_stack(t) for t in trades]
            payload["inline_trades"] = [p for p in parsed if p is not None]

        unknown = set(doc) - {"trades", "amount", "random_sequence"}
        if unknown:
            missing.append(f"未知字段 {', '.join(sorted(unknown))}")

        status = Status.PARTIAL if missing else Status.PARSED
        store.add(
            Fact(
                kind="trade",
                payload=payload,
                prov=Prov(input="src", file=file_label),
                status=status,
                missing=tuple(missing),
            )
        )
        record(store, file_label, FAMILY, facts=1, missing=tuple(missing))

    # ---- 公共 ----------------------------------------------------------

    def _load(self, path: Path, file_label: str, store: FactStore) -> dict | None:
        try:
            doc = read_json(path)
        except (OSError, ValueError) as exc:
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error=str(exc))
            return None
        if not isinstance(doc, dict):
            record(store, file_label, FAMILY, status=LedgerStatus.FAILED, error="顶层不是对象")
            return None
        return doc
