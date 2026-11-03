"""按内容形状识别目录归属，而不是按版本号查目录名。

数据包里的目录名随版本变化（`recipe` ⇄ `recipes`、`tags/item` ⇄ `tags/items`），
形状不变。判不出来的一律记 UNKNOWN，不猜。

只区分这几类形状，其余交给「目录名 ↔ 注册表」锚定（见 `anchors.py`）。
之所以要按形状判，是因为这些目录的名称会变（单复数、`villager_trade` 这类描述性名），
而形状是格式本身的一部分。
"""

from __future__ import annotations

RECIPE_STRONG_KEYS = frozenset({"result", "pattern", "ingredients"})

# 交易的两层形状（实测 26.3）：
# 单条交易 `{gives, wants, max_uses, ...}`，交易组 `{amount, trades: "#tag"}`。
# 两者都不带 `type`，带 `random_sequence` 的交易组要与战利品表区分，
# 所以交易组必须先于战利品表判定。
TRADE_OFFER_KEYS = frozenset({"gives", "wants"})
TRADE_SET_KEYS = frozenset({"trades", "amount"})

# 主导形状的绝对样本数下限。防止「大量未知 + 个别噪点」被当成目录归属。
MIN_SHAPE_HITS = 3

TAG = "tag"
RECIPE = "recipe"
LOOT_TABLE = "loot_table"
TRADE_OFFER = "trade_offer"
TRADE_SET = "trade_set"
BLOCK_TRANSFORM = "block_transform"
TYPED_ONLY = "typed_only"
UNKNOWN = "unknown"

# 方块变换的判定键：条目里必有 `block_state_provider`（顶层是数组，不是对象）。
BLOCK_TRANSFORM_KEYS = frozenset({"block_state_provider"})


def classify(doc: object) -> str:
    """给单个 JSON 文档归类。只认形状，不认语义。

    `result` / `pattern` / `ingredients` 是配方独占的强信号。
    `input` / `source` / `target` 一类键在 worldgen（density_function 的 `input`、
    netherrack_replace_blobs 的 `target`、randomized_int 的 `source`）里同样出现，
    不能当配方信号用，否则会把 `worldgen/density_function` 误判成配方目录。

    判定顺序有依赖：交易组带 `random_sequence`，若不先判会被当成战利品表。

    **顶层是数组**的情况只有方块变换（实测：其余注册表都是单对象）。
    数组里每个条目都带 `block_state_provider` 才认，避免把结构模板的
    调色板数组当成变换表。
    """
    if isinstance(doc, list):
        if doc and all(
            isinstance(item, dict) and BLOCK_TRANSFORM_KEYS <= set(item) for item in doc
        ):
            return BLOCK_TRANSFORM
        return UNKNOWN
    if not isinstance(doc, dict):
        return UNKNOWN
    keys = set(doc)
    if "values" in keys and keys <= {"values", "replace"}:
        return TAG
    if keys >= TRADE_OFFER_KEYS:
        return TRADE_OFFER
    if keys >= TRADE_SET_KEYS and "trades" in keys:
        return TRADE_SET
    # `random_sequence` 单独也要认：可疑方块的战利品表只有 `type` + `random_sequence`、
    # 没有 `pools`，漏掉它会把空表当成未知。
    if "pools" in keys or "random_sequence" in keys:
        return LOOT_TABLE
    if "type" not in keys:
        return UNKNOWN
    if keys & RECIPE_STRONG_KEYS:
        return RECIPE
    return TYPED_ONLY


def resolve_dominant(counts: dict[str, int], threshold: float = 0.5) -> tuple[str | None, float]:
    """取主导形状；低于阈值返回 (None, 占比)，由调用方记 UNKNOWN。

    `TYPED_ONLY` 不进分母：这类文档只有 `type`、无任何配方特征，可能是配方的特殊变体
    （`crafting_special_*` 在 JSON 里只写 `type`），也可能是别的注册表条目。
    把它计入分母会让 `recipe` 目录因特殊配方而虚低；但绝对样本数仍要过闸，
    否则「55 个未知 + 1 个命中」会被当成配方目录。
    """
    total = sum(counts.values())
    if not total:
        return None, 0.0
    decisive = {k: v for k, v in counts.items() if k not in (TYPED_ONLY, UNKNOWN)}
    if not decisive:
        return None, 0.0
    shape, hits = max(decisive.items(), key=lambda item: (item[1], item[0]))
    denominator = total - counts.get(TYPED_ONLY, 0)
    ratio = hits / denominator if denominator else 0.0
    if hits < MIN_SHAPE_HITS or ratio < threshold:
        return None, ratio
    return shape, ratio
