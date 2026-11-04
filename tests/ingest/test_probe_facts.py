"""探测结果事实化、族级不可用登记、worldgen 双路对账。

三项都是方案里写了但实现还没落到产物上的：

| 项 | 方案条款 | 不做的话会怎样 |
|---|---|---|
| `profile` 事实 | §3.3 事实种类 | 下游读不到「当时按什么分派解析」 |
| `pack_delta` 登记 | §3.3 + §11 + 红线 3 | 「没地形包」与「实现漏了」在产物上分不清 |
| worldgen 对账 | §3.2 | 未来某版两侧都有时静默只用一侧 |
"""

from __future__ import annotations

import unittest

from ra.probe.profile import Profile
from ra.probe.worldgen import WORLDGEN_SUBDIR_ALIASES, _anchors, _crosscheck


def _pack(label: str):
    return pack(label)


def _ingest(label: str):
    from tests.support import store

    return store(label)


from tests.support import pack, why

class WorldgenCrosscheckTest(unittest.TestCase):
    """双路对账的判据不对称：数据包多是正常的，运行期多才是异常。"""

    def test_datapack_superset_is_not_an_anomaly(self) -> None:
        """数据包是源文件全集，运行期只含注册成功的条目 → 数据包多是正常的。"""
        profile = Profile(label="t", content_commit="x")
        datapack = [("minecraft", "biome", {"plains", "desert", "swamp"})]
        reports = [("biome", {"plains"})]
        _crosscheck(datapack, reports, profile)
        self.assertEqual(profile.unresolved, [])
        self.assertTrue(any("对账通过" in n for n in profile.notes))

    def test_reports_only_entry_is_an_anomaly(self) -> None:
        """运行期有而数据包没有 = 注册成功但源文件缺失，这是真异常。"""
        profile = Profile(label="t", content_commit="x")
        datapack = [("minecraft", "biome", {"plains"})]
        reports = [("biome", {"plains", "ghost_biome"})]
        _crosscheck(datapack, reports, profile)
        self.assertEqual(len(profile.unresolved), 1)
        self.assertIn("ghost_biome", profile.unresolved[0])

    def test_subdir_aliases_are_applied(self) -> None:
        """两侧子目录名不同：数据包 `feature`，运行期 `configured_feature`。"""
        self.assertEqual(WORLDGEN_SUBDIR_ALIASES["configured_feature"], "feature")
        profile = Profile(label="t", content_commit="x")
        datapack = [("minecraft", "feature", {"ore_diamond"})]
        reports = [("configured_feature", {"ore_diamond"})]
        _crosscheck(datapack, reports, profile)
        self.assertEqual(profile.unresolved, [], "归一后应完全一致")

    def test_reports_subdir_without_counterpart_is_noted(self) -> None:
        profile = Profile(label="t", content_commit="x")
        datapack = [("minecraft", "feature", {"ore_diamond"})]
        reports = [("some_new_registry", {"x"})]
        _crosscheck(datapack, reports, profile)
        self.assertTrue(any("some_new_registry" in n for n in profile.notes))

    def test_anchors_merge_same_subdir(self) -> None:
        """同名子目录跨命名空间要并成一个锚点键。"""
        anchors = _anchors(
            [
                ("minecraft", "biome", {"plains"}),
                ("mypack", "biome", {"custom"}),
            ]
        )
        self.assertEqual(anchors["worldgen/biome"], {"plains", "custom"})


class ProfileFactBase:
    label = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.store = _ingest(cls.label)

    def test_profile_fact_exists(self) -> None:
        facts = self.store.of_kind("profile")
        self.assertEqual(len(facts), 1, "profile 事实应恰好一条")

    def test_profile_fact_carries_dispatch_decisions(self) -> None:
        """事实要能独立回答「当时按什么方言/来源解析」。"""
        payload = self.store.of_kind("profile")[0].payload
        for key in (
            "label",
            "content_commit",
            "loot_dialect",
            "worldgen_source",
            "components_layout",
            "dirs",
        ):
            self.assertIn(key, payload, f"缺 {key}，下游无法复算分派")
        self.assertIn("dialect", payload["loot_dialect"])
        self.assertTrue(payload["dirs"], "目录归属为空")

    def test_profile_fact_has_provenance(self) -> None:
        fact = self.store.of_kind("profile")[0]
        self.assertEqual(fact.prov.input, "src")
        self.assertTrue(fact.prov.file)

    def test_pack_delta_is_declared_unavailable(self) -> None:
        """没地形包要显式登记，不能靠「一条也没有」表达。"""
        families = {item["family"] for item in self.store.unavailable}
        self.assertIn("pack_delta", families)

    def test_worldgen_source_matches_input_shape(self) -> None:
        payload = self.store.of_kind("profile")[0].payload
        self.assertIn(payload["worldgen_source"], ("datapack", "reports", "both", "none"))


@unittest.skipUnless(_pack("26.3"), why("26.3"))
class ProfileFact263Test(ProfileFactBase, unittest.TestCase):
    label = "26.3"

    def test_worldgen_comes_from_datapack(self) -> None:
        payload = self.store.of_kind("profile")[0].payload
        self.assertEqual(payload["worldgen_source"], "datapack")
        self.assertGreater(len(payload["worldgen_counts"]), 10)


@unittest.skipUnless(_pack("1.18.2"), why("1.18.2"))
class ProfileFact1182Test(ProfileFactBase, unittest.TestCase):
    label = "1.18.2"

    def test_worldgen_comes_from_reports(self) -> None:
        payload = self.store.of_kind("profile")[0].payload
        self.assertEqual(payload["worldgen_source"], "reports")


if __name__ == "__main__":
    unittest.main()
