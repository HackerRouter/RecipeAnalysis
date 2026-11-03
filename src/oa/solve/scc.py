"""强连通分量：把「互相等待」算准。

归因需要知道「这个节点是不是在环里且环无外部入口」。用 DFS 找环有两问题：

1. **慢**：回溯时移除 `seen`，同一节点被反复访问，最坏指数级。
   实测 1658 个物品逐个找环时卡住数分钟
2. **判据错**：找到一条回到起点的路径 ≠ 「这一组互相等待且无外部入口」。
   实测 `furnace` 被误判成 `cycle_no_entry`——它确实有
   `block:furnace ⇄ item:furnace` 的环，但**另有配方入口**，不成立

所以改用 SCC：一次把图分解成强连通分量，之后 O(1) 查询「两个节点是否同属一个环」。
「无外部入口」= 该分量的所有节点都不可达。

迭代实现，避免 13000+ 节点时递归爆栈。
"""

from __future__ import annotations


def strongly_connected(
    graph: dict[str, set[str]],
    nodes: set[str] | None = None,
) -> dict[str, int]:
    """Kosaraju（迭代版），返回 `节点 → 分量编号`。

    `graph` 是 `节点 → 后继`。未在 `graph` 里出现的节点也会被分配分量。
    """
    vertices = set(graph)
    if nodes:
        vertices |= nodes
    for targets in graph.values():
        vertices |= targets

    # 第一遍：DFS 求完成序
    order: list[str] = []
    visited: set[str] = set()
    for root in sorted(vertices):
        if root in visited:
            continue
        stack: list[tuple[str, bool]] = [(root, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
                continue
            if node in visited:
                continue
            visited.add(node)
            stack.append((node, True))
            for nxt in sorted(graph.get(node, ())):
                if nxt not in visited:
                    stack.append((nxt, False))

    # 反向图
    reverse: dict[str, set[str]] = {}
    for node, targets in graph.items():
        for target in targets:
            reverse.setdefault(target, set()).add(node)

    # 第二遍：按完成序的逆序在反向图上 DFS
    component: dict[str, int] = {}
    index = 0
    for node in reversed(order):
        if node in component:
            continue
        stack = [node]
        component[node] = index
        while stack:
            current = stack.pop()
            for prev in sorted(reverse.get(current, ())):
                if prev not in component:
                    component[prev] = index
                    stack.append(prev)
        index += 1

    return component


def component_members(component: dict[str, int]) -> dict[int, list[str]]:
    members: dict[int, list[str]] = {}
    for node, cid in component.items():
        members.setdefault(cid, []).append(node)
    return {cid: sorted(values) for cid, values in members.items()}
