"""反编译源码根定位：靠特征文件，不靠目录布局。

踩过的坑：曾用候选目录表（`src/main/java`、`java`、`src`…）逐个试探。
候选表永远补不全——反编译产物直接是根下 `net/`，多层前缀仓库又是另一种，
每遇到新布局就得加一行，而漏加时是静默失配。

改为读全量文件清单后找特征文件 `net/minecraft/WorldVersion.java`，
命中位置的前缀就是反编译源码根，与仓库怎么组织无关。

特征文件的选择标准：每个版本都在、包名稳定、语义上属于「版本标识」。
不用 commit message 或 tag 判断——各仓库的提交习惯不一致，不能假设。
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from oa.errors import InputError
from oa.inputs.source import FEATURE_FILES, find_source_path, find_source_paths

WORLD_VERSION = "package net.minecraft;\npublic interface WorldVersion {}\n"


def _make_tree(base: Path, files: dict[str, str]) -> tuple[Path, str]:
    """造仓库并返回树对象 SHA。

    用 `write-tree` 而不是 `commit`：验证只需要 treeish，不需要提交记录，
    也就不会碰到本机的签名配置。
    """
    repo = base / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    tree = subprocess.run(
        ["git", "-C", str(repo), "write-tree"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, tree


class LayoutTest(unittest.TestCase):
    """四种实际见过的布局，同一条定位逻辑都要命中。"""

    CASES = {
        "gradle": ("src/main/java", "src/main/java/net/minecraft/WorldVersion.java"),
        "export": ("src", "src/net/minecraft/WorldVersion.java"),
        "decompiled": ("", "net/minecraft/WorldVersion.java"),
        "nested": (
            "decompiled/26.3/src",
            "decompiled/26.3/src/net/minecraft/WorldVersion.java",
        ),
    }

    def test_all_layouts_resolve(self) -> None:
        for name, (expected, rel) in self.CASES.items():
            with self.subTest(layout=name), tempfile.TemporaryDirectory() as tmp:
                repo, tree = _make_tree(Path(tmp), {rel: WORLD_VERSION})
                self.assertEqual(find_source_path(repo, tree), expected)

    def test_feature_file_is_version_identity(self) -> None:
        # 特征文件必须是与版本语义绑定的类，不能是任一普通类
        self.assertIn("net/minecraft/WorldVersion.java", FEATURE_FILES)

    def test_parallel_trees_are_reported_not_guessed(self) -> None:
        # 一个提交里放多份反编译源码树是可能的组织方式；静默取第一份会分析错版本
        with tempfile.TemporaryDirectory() as tmp:
            repo, tree = _make_tree(
                Path(tmp),
                {
                    "1.18.2/src/net/minecraft/WorldVersion.java": WORLD_VERSION,
                    "26.3/src/net/minecraft/WorldVersion.java": WORLD_VERSION,
                },
            )
            self.assertEqual(find_source_paths(repo, tree), ["1.18.2/src", "26.3/src"])
            with self.assertRaises(InputError) as ctx:
                find_source_path(repo, tree)
            self.assertIn("source_path", str(ctx.exception))

    def test_no_source_tree_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, tree = _make_tree(Path(tmp), {"README.md": "x\n"})
            self.assertEqual(find_source_paths(repo, tree), [])
            self.assertIsNone(find_source_path(repo, tree))


if __name__ == "__main__":
    unittest.main()
