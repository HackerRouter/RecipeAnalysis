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
"""

from __future__ import annotations

from pathlib import Path

from ..facts import Fact, FactStore, LedgerStatus, Prov, Status
from ..probe.profile import Profile
from ..util.jsonio import read_json
from .base import Adapter, iter_json_files, record, rel_posix
from ..paths import pack_data

FAMILY = "trade"

LAYER_OFFER = "offer"
LAYER_SET = "set"


def parse_item_stack(node: object) -> dict | None:
    """`{id, count, components}` → 归一形状。也接受裸字符串。"""
    if isinstance(node, str):
        return {"id": node, "count": 1}
    if not isinstance(node, dict):
        return None
    ident = node.get("id") or node.get("item")
    if not isinstance(ident, str):
        return None
    out: dict = {"id": ident}
    count = node.get("count", node.get("amount", 1))
    out["count"] = count if isinstance(count, int) else 1
    for key in ("components", "count_range"):
        if key in node:
            out[key] = node[key]
    # 未归一的字段原样留着，由 IR 决定是不是前置
    rest = {k: v for k, v in node.items() if k not in ("id", "item", "count", "amount")}
    if rest:
        out["extra"] = rest
    return out


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

        for registry, layer in (
            ("villager_trade", LAYER_OFFER),
            ("trade_set", LAYER_SET),
        ):
            claim = profile.dirs.get(registry)
            if claim is None:
                continue
            ns, _, rel = claim.path.partition("/")
            root = pack_data(pack_dir) / ns / rel
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
                    self._offer(path, pack_dir, ns, store)
                else:
                    self._set(path, pack_dir, ns, store)

    # ---- 单条交易 ------------------------------------------------------

    def _offer(self, path: Path, pack_dir: Path, namespace: str, store: FactStore) -> None:
        file_label = rel_posix(path, pack_dir)
        doc = self._load(path, file_label, store)
        if doc is None:
            return

        missing: list[str] = []
        gives = parse_item_stack(doc.get("gives"))
        wants = parse_item_stack(doc.get("wants"))
        if gives is None:
            missing.append("gives 无法解析")
        if wants is None:
            missing.append("wants 无法解析")

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

        payload = {
            "layer": LAYER_OFFER,
            "trade": _trade_id(file_label, "villager_trade", namespace),
            "profession": _segment(file_label, "villager_trade", 0),
            "level": _level(file_label, "villager_trade"),
            "gives": gives,
            "wants": wants,
            "additional_wants": additional,
        }

        # 不参与获取路径判定、但下游难度可能要的字段，原样透传
        meta = {
            key: doc[key]
            for key in ("max_uses", "reputation_discount", "xp", "price_multiplier")
            if key in doc
        }
        if meta:
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
        record(store, file_label, FAMILY, facts=1)

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

        payload = {
            "layer": LAYER_SET,
            "set": _trade_id(file_label, "trade_set", namespace),
            "profession": _segment(file_label, "trade_set", 0),
            "level": _level(file_label, "trade_set"),
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
        record(store, file_label, FAMILY, facts=1)

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


def _trade_id(file_label: str, dirname: str, namespace: str) -> str:
    marker = f"/{dirname}/"
    if marker in file_label:
        return f"{namespace}:{file_label.partition(marker)[2][:-5]}"
    return file_label[:-5]


def _segment(file_label: str, dirname: str, index: int) -> str | None:
    """交易路径是 `<职业>/<等级>/<名>.json`，取第 index 段。"""
    marker = f"/{dirname}/"
    if marker not in file_label:
        return None
    parts = file_label.partition(marker)[2].split("/")
    return parts[index] if len(parts) > index + 1 else None


def _level(file_label: str, dirname: str) -> int | None:
    """取等级。交易组是 `level_N.json`，单条交易是 `<职业>/<N>/<名>.json`。"""
    marker = f"/{dirname}/"
    if marker not in file_label:
        return None
    parts = file_label.partition(marker)[2].split("/")

    for part in parts[1:]:
        stem = part[:-5] if part.endswith(".json") else part
        if stem.startswith("level_"):
            tail = stem[len("level_") :]
            return int(tail) if tail.isdigit() else None
        if stem.isdigit():
            return int(stem)
    return None
