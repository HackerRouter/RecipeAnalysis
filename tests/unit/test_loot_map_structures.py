"""`exploration_map` 的目的地展开。

`destination` 写的是结构**标签**，产物对得上的是结构 id。展开规则有三条要钉住：

- 嵌套标签逐层进去（标签里写 `#other` 是常态）
- 直接写结构名时不查表
- 查不到就给空列表，不猜名字；标签成环也不能死循环
"""

from __future__ import annotations

import unittest

from ra.adapters.loot import annotate_products


def _payload(destination: str | None, name: str = "minecraft:map") -> dict:
    function: dict = {"function": "minecraft:exploration_map", "decoration": "red_x"}
    if destination is not None:
        function["destination"] = destination
    return {
        "pools": [
            {
                "entries": [
                    {
                        "kind": "item",
                        "name": name,
                        "functions": [function],
                    }
                ]
            }
        ]
    }


def _entry(payload: dict) -> dict:
    return payload["pools"][0]["entries"][0]


TAGS = {
    "ns:outer": ("#ns:inner",),
    "ns:inner": ("minecraft:buried_treasure",),
    "ns:loop_a": ("#ns:loop_b",),
    "ns:loop_b": ("#ns:loop_a",),
}


class MapStructuresTest(unittest.TestCase):
    def test_nested_tag_is_expanded(self) -> None:
        payload = _payload("#ns:outer")
        annotate_products(payload, TAGS)
        self.assertEqual(_entry(payload)["map_structures"], ["minecraft:buried_treasure"])

    def test_bare_id_is_itself(self) -> None:
        payload = _payload("minecraft:buried_treasure")
        annotate_products(payload, TAGS)
        self.assertEqual(_entry(payload)["map_structures"], ["minecraft:buried_treasure"])

    def test_unknown_tag_yields_empty_list(self) -> None:
        """展开不到就留空列表：说明算过但没成员，不是没算过。"""
        payload = _payload("#ns:missing")
        annotate_products(payload, TAGS)
        self.assertEqual(_entry(payload)["map_structures"], [])

    def test_tag_cycle_terminates(self) -> None:
        payload = _payload("#ns:loop_a")
        annotate_products(payload, TAGS)
        self.assertEqual(_entry(payload)["map_structures"], [])

    def test_missing_destination_is_counted_not_guessed(self) -> None:
        payload = _payload(None)
        count = annotate_products(payload, TAGS)
        self.assertEqual(count, 1)
        self.assertNotIn("map_structure", _entry(payload))
        self.assertNotIn("map_structures", _entry(payload))
        self.assertEqual(_entry(payload)["product_id"], "minecraft:filled_map")


if __name__ == "__main__":
    unittest.main()
