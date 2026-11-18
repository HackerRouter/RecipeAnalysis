"""挖掘可查表的形状测试（`ra export` 的下游视图）。

表只由事实派生：行数等于对应种类的事实数，列齐、排序稳定、缺值为 null。
不在这里校验具体数值——数值的对照在 `tests/code/test_mining.py`。
"""

from __future__ import annotations

import unittest

from ra.report.mining_tables import (
    BLOCK_COLUMNS,
    MATERIAL_COLUMNS,
    TABLE_BLOCKS,
    TABLE_MATERIALS,
    TABLE_TOOLS,
    TOOL_COLUMNS,
    build_mining_tables,
    mining_formula,
)

from tests.support import pack, store, why


class _MiningTablesBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.facts = store(cls.label)
        cls.tables = build_mining_tables(cls.facts)

    def count(self, kind: str) -> int:
        return sum(
            1 for fact in self.facts.of_kind("mining") if fact.payload["form"] == kind
        )

    def test_row_counts_match_facts(self) -> None:
        self.assertEqual(len(self.tables[TABLE_BLOCKS]), self.count("block"))
        self.assertEqual(len(self.tables[TABLE_TOOLS]), self.count("tool"))
        self.assertEqual(len(self.tables[TABLE_MATERIALS]), self.count("material"))

    def test_columns_are_complete(self) -> None:
        cases = (
            (TABLE_BLOCKS, "block", BLOCK_COLUMNS),
            (TABLE_TOOLS, "item", TOOL_COLUMNS),
            (TABLE_MATERIALS, "material", MATERIAL_COLUMNS),
        )
        for table, key, columns in cases:
            for row in self.tables[table]:
                self.assertEqual(tuple(row), columns)
                self.assertIsNotNone(row[key])

    def test_rows_are_sorted(self) -> None:
        for table, key in (
            (TABLE_BLOCKS, "block"),
            (TABLE_TOOLS, "item"),
            (TABLE_MATERIALS, "material"),
        ):
            keys = [row[key] for row in self.tables[table]]
            self.assertEqual(keys, sorted(keys))

    def test_formula_is_not_empty(self) -> None:
        formula = mining_formula(self.facts)
        self.assertIsNotNone(formula)
        self.assertIn("divisors", formula)
        self.assertEqual(formula["divisors"]["correct_tool"], 30)


@unittest.skipUnless(pack("26.3"), why("26.3"))
class MiningTables263Test(_MiningTablesBase, unittest.TestCase):
    label = "26.3"


@unittest.skipUnless(pack("1.18.2"), why("1.18.2"))
class MiningTables1182Test(_MiningTablesBase, unittest.TestCase):
    label = "1.18.2"


if __name__ == "__main__":
    unittest.main()
