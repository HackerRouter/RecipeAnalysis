"""探测层的锚点合并：数据包自带的命名空间不能把 `minecraft` 的锚点挤掉。

数据包几乎都会带自己的命名空间（`data/<包名>/worldgen/...`）。曾经只取
`profile.namespaces[0]`，排序后正好是包自己的命名空间，于是 `minecraft` 侧的
注册表锚点全部缺失，标签归属退化成「按目录名」，且没有任何报错——表现是标签
子目录一个个从 `tag_dirs` 里消失、台账冒出成片「没有适配器认领该文件」。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ra.probe.build import probe_pack_anchors


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")


class PackAnchorsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        for name in ("armorer", "farmer"):
            _touch(self.data / "minecraft" / "villager_trade" / f"{name}.json")
        for name in ("x", "y"):
            _touch(self.data / "fasbingo" / "worldgen" / "density_function" / f"{name}.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_minecraft_anchors_survive_extra_namespace(self) -> None:
        anchors = probe_pack_anchors(self.data, ["fasbingo", "minecraft"])
        self.assertEqual(anchors["villager_trade"], {"armorer", "farmer"})
        self.assertIn("worldgen", anchors)

    def test_single_namespace_is_unchanged(self) -> None:
        anchors = probe_pack_anchors(self.data, ["minecraft"])
        self.assertEqual(set(anchors), {"villager_trade"})

    def test_empty_namespace_list_falls_back_to_minecraft(self) -> None:
        anchors = probe_pack_anchors(self.data, [])
        self.assertEqual(anchors["villager_trade"], {"armorer", "farmer"})


if __name__ == "__main__":
    unittest.main()
