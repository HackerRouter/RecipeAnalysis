"""标签成员表：按注册表索引，递归展开嵌套。

`tag` 节点在 IR 里只有一个含义：**「其中有任一个」**。
`bridge/tag` 把成员编成 `tag ← item`，所以 tag 为真当且仅当某个成员为真。

但「放置/掉落时从 tag 里随机取一个」是**另一种**语义：tag 为真之后，
每个成员都可能产出。这种情形不能用 `tag ← item` 反推，必须显式展开成
`item ← ...`（每个成员各一条）。

存在性语义给出依据：随机选择意味着每个成员被选中的概率非零，
世界无限，于是每个成员都可能在某处出现。这与「定义了就是有」是同一条语义。

两处用到展开：`families/worldgen`（方块标签放置）、`families/loot`（掉落标签）。
抽到这里是为了不让两份实现漂移——早先它们各自漏过不同的写法。
"""

from __future__ import annotations

from ..facts import Fact


class TagMembers:
    """`{注册表 → {标签 → 成员集合}}`，成员已递归展开。"""

    def __init__(self, tag_facts: list[Fact]) -> None:
        direct: dict[str, dict[str, list[str]]] = {}
        for fact in tag_facts:
            payload = fact.payload
            registry = payload.get("registry")
            tag_id = payload.get("tag")
            if not isinstance(registry, str) or not isinstance(tag_id, str):
                continue
            members: list[str] = []
            for member in payload.get("values") or []:
                ident = member if isinstance(member, str) else None
                if ident is None and isinstance(member, dict):
                    ident = member.get("id")
                if isinstance(ident, str):
                    # 老格式的 `#` 前缀：适配器通常已剥掉，这里兜底
                    members.append(ident.lstrip("#"))
            for ident in payload.get("nested") or []:
                if isinstance(ident, str):
                    members.append(ident)
            direct.setdefault(registry, {})[tag_id] = members

        self._resolved: dict[str, dict[str, set[str]]] = {}
        for registry, table in direct.items():
            cache: dict[str, set[str]] = {}

            def walk(tag_id: str, seen: frozenset[str], *, _table=table, _cache=cache) -> set[str]:
                if tag_id in _cache:
                    return _cache[tag_id]
                if tag_id in seen:
                    return set()
                out: set[str] = set()
                for member in _table.get(tag_id, ()):
                    # 成员本身也是本注册表里的标签 → 递归；否则当条目
                    if member in _table:
                        out |= walk(member, seen | {tag_id})
                    else:
                        out.add(member)
                _cache[tag_id] = out
                return out

            self._resolved[registry] = {tag_id: walk(tag_id, frozenset()) for tag_id in table}

    def members(self, registry: str, tag_id: str) -> set[str]:
        """`registry` 可带命名空间。标签不存在时返回空集合。"""
        table = self._resolved.get(registry) or self._resolved.get(
            registry.split(":", 1)[-1], {}
        )
        return set(table.get(tag_id, set()))

    def has(self, registry: str, tag_id: str) -> bool:
        table = self._resolved.get(registry) or self._resolved.get(
            registry.split(":", 1)[-1], {}
        )
        return tag_id in table
