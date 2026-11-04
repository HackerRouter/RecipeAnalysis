"""[unit] `ra guide` 的渲染：输入取自 profile 与产物 JSON，不读文件。"""

from __future__ import annotations

import unittest

from ra.report.guide import render_guide


def _profile(**overrides) -> dict:
    base = {
        "label": "9.9",
        "content_commit": "abc1234",
        "source_repo": "path/to/repo",
        "version": {"pack_data_major": 1, "world_version": 2, "protocol_version": 3},
        "reports": {
            "kind": "datagen",
            "root": "cache/reports",
            "components_layout": "components",
            "components_dir": "minecraft/components/item",
            "datapack_capability": "ok",
            "block_report": "ok",
        },
        "registries": {"minecraft:item": 10},
        "namespaces": ["minecraft"],
        "dirs": {
            "recipe": {"registry": "recipe", "path": "minecraft/recipe",
                       "files": 5, "shape": "recipe", "coverage": 1.0, "status": "ok"},
        },
        "tag_dirs": {
            "minecraft:item": {"registry": "minecraft:item",
                               "path": "minecraft/tags/item", "files": 3,
                               "coverage": 1.0, "status": "ok"},
        },
        "templates": {"dir": "minecraft/structure", "ext": None, "source": "jar",
                      "root": "cache/structures", "dir_src": None, "files": 7},
        "worldgen": {"source": "datapack", "counts": {"minecraft/biome": 4}},
        "loot_dialect": {"dialect": "modern", "evidence": {"modern": 2}},
        "excluded_dirs": ["minecraft/datapacks"],
        "notes": ["minecraft/foo 形状不明确"],
        "unresolved": [],
        "jar": {"path": "server.jar", "sha256": "deadbeef"},
    }
    base.update(overrides)
    return base


class GuideRenderTest(unittest.TestCase):
    def test_renders_each_section_from_profile(self):
        text = render_guide(profile=_profile())
        for heading in ("版本与 provenance", "输入布局", "数据包目录归属",
                        "标签子目录归属", "结构模板", "世界生成", "战利品方言",
                        "整棵排除的目录", "探测到但未归属的目录", "未决项", "复算"):
            self.assertIn(f"## {heading}", text, heading)

    def test_carries_probe_conclusions(self):
        text = render_guide(profile=_profile())
        self.assertIn("minecraft/recipe", text)
        self.assertIn("datagen", text)
        self.assertIn("minecraft/structure", text)
        self.assertIn("minecraft/datapacks", text)
        self.assertIn("形状不明确", text)

    def test_products_section_only_when_available(self):
        bare = render_guide(profile=_profile())
        self.assertNotIn("## 事实与规则产出", bare)

        with_products = render_guide(
            profile=_profile(),
            facts_summary={"kinds": {"recipe": 5}, "status": {"parsed": 5},
                           "unavailable_families": [
                               {"family": "components", "reason": "无报告", "note": "略"}]},
            coverage={"rule_families": {"recipes": 5}, "nodes_by_sort": {"item": 10}},
            run={"reachability": {"identities": 10,
                                  "by_status": {"true": 9, "false": 1}, "rate": 0.9}},
        )
        self.assertIn("## 事实与规则产出", with_products)
        self.assertIn("components", with_products)
        self.assertIn("90%", with_products)

    def test_missing_optional_fields_do_not_crash(self):
        minimal = {"label": "9.9"}
        text = render_guide(profile=minimal)
        self.assertIn("# 适配指南：9.9", text)
        self.assertIn("没有未归属的目录", text)
        self.assertIn("无未决项", text)

    def test_null_commit_is_called_out(self):
        text = render_guide(profile=_profile(content_commit=None))
        self.assertIn("不可复算代码侧结论", text)

    def test_repo_paths_are_relativized(self):
        profile = _profile(source_repo="/work/repo-mirror",
                           templates={"dir": "d", "root": "/work/repo/.cache/s",
                                      "files": 1, "source": "jar"})
        text = render_guide(profile=profile, root="/work/repo")
        self.assertIn("<REPO_ROOT>/.cache/s", text)
        self.assertNotIn("/work/repo/.cache", text)
        # 仓库外路径只留最后一级
        self.assertIn("…/repo-mirror", text)
        self.assertNotIn("/work/repo-mirror", text)

    def test_template_source_fallback_is_explained(self):
        src = render_guide(profile=_profile(
            templates={"dir": "d", "source": "src", "files": 1}))
        self.assertIn("palette", src)
        none = render_guide(profile=_profile(
            templates={"dir": None, "source": "none", "files": 0}))
        self.assertIn("未找到模板目录", none)


if __name__ == "__main__":
    unittest.main()
