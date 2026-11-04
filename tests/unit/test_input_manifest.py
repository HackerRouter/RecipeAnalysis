"""输入配置：一份反编译源码仓 + 每版本指明用哪个提交。

形态是用户定的：不是每版本一个仓库，也不是 `inputs/` 整体一个仓库，
而是「独立反编译源码仓 + 各版本段写 content_commit」。

提交号必须显式给出，不推导：
- 不猜 HEAD——一个仓库的工作树只停在一个版本，HEAD 只对应其中一份快照
- 不读 commit message 或 tag 匹配版本号——各仓库的提交习惯不一致，不能假设

`import_commit` 是「显式给出」的例外：配置为空时才去问一次仓库，
取回后写回配置，此后以配置为准。
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ra.inputs.manifest import load_manifest, reconcile


def _init_repo(path: Path) -> Path:
    """造一个仓库，返回仓库路径。不创建提交，避免触到本机签名配置。"""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
    target = path / "src" / "net" / "minecraft" / "WorldVersion.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("package net.minecraft;\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "write-tree"], check=True, capture_output=True)
    return path


class ManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.inputs = self.root / "inputs"
        self.pack = self.inputs / "26.3"
        (self.pack / "java").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text("x\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, body: str) -> None:
        (self.inputs / "manifest.toml").write_text(body, encoding="utf-8")

    def test_commit_and_repo_are_read_separately(self) -> None:
        self._write(
            "[source]\n"
            'repo = "mc-src"\n'
            '["26.3"]\n'
            'content_commit = "abc123"\n'
            '"java_home" = "/opt/jdk"\n'
        )
        manifest = load_manifest(self.pack)
        self.assertEqual(manifest.content_commit, "abc123")
        self.assertEqual(manifest.source_repo, (self.root / "mc-src").resolve())
        self.assertEqual(manifest.java_home, "/opt/jdk")
        # [source] 不是版本段，不能出现在标签里
        self.assertIsNone(manifest.source_path)

    def test_absolute_repo_path_is_kept(self) -> None:
        repo = _init_repo(self.root / "elsewhere")
        self._write(f'[source]\nrepo = "{repo.as_posix()}"\n["26.3"]\n')
        manifest = load_manifest(self.pack)
        self.assertEqual(manifest.source_repo, repo.resolve())

    def test_commit_absent_means_use_existing_tree(self) -> None:
        self._write('["26.3"]\n"java_home" = "/opt/jdk"\n')
        manifest = load_manifest(self.pack)
        self.assertIsNone(manifest.content_commit)
        self.assertIsNone(manifest.source_repo)

    def test_source_path_is_optional_override(self) -> None:
        self._write(
            '["26.3"]\n'
            'content_commit = "abc123"\n'
            '"source_path" = "decompiled/26.3/src"\n'
        )
        self.assertEqual(load_manifest(self.pack).source_path, "decompiled/26.3/src")

    def test_reconcile_keeps_known_keys_and_drops_stale(self) -> None:
        self._write(
            '["26.3"]\n'
            'content_commit = "abc123"\n'
            '"source_path" = "src"\n'
            'legacy_key = "x"\n'
            '"java_home" = "/opt/jdk"\n'
        )
        reconcile(self.root)
        text = (self.inputs / "manifest.toml").read_text(encoding="utf-8")
        self.assertIn("content_commit", text)
        self.assertIn("source_path", text)
        self.assertIn("/opt/jdk", text)
        self.assertNotIn("legacy_key", text)

    def test_reconcile_writes_source_section_hint(self) -> None:
        # 首次生成才写提示；文件已对齐时不重写，免得每跑一次就冲掉手写注释
        (self.inputs / "manifest.toml").unlink(missing_ok=True)
        reconcile(self.root)
        text = (self.inputs / "manifest.toml").read_text(encoding="utf-8")
        self.assertIn("[source]", text)
        self.assertIn("repo =", text)

    def test_reconcile_preserves_configured_repo(self) -> None:
        """重写时已配置的 repo 必须原样保留。

        `[source]` 不在版本段里，独立于 sections 读取；若重写时只写提示，
        加的版本一次就把它注释掉，下次运行找不到反编译源码仓。
        """
        self._write('[source]\nrepo = "mc-src"\n["26.3"]\ncontent_commit = "abc123"\n')
        # 新增一个版本目录触发重写
        (self.inputs / "1.20.1" / "java").mkdir(parents=True)
        reconcile(self.root)

        text = (self.inputs / "manifest.toml").read_text(encoding="utf-8")
        self.assertIn('[source]\nrepo = "mc-src"', text)
        self.assertNotIn('# repo =', text)
        # 重写后仍可被读回，且新版本段已补上
        manifest = load_manifest(self.pack)
        self.assertEqual(manifest.source_repo, (self.root / "mc-src").resolve())
        self.assertEqual(manifest.content_commit, "abc123")
        self.assertIn('["1.20.1"]', text)

    def test_reconcile_drops_removed_version_but_keeps_repo(self) -> None:
        self._write('[source]\nrepo = "mc-src"\n["26.3"]\n["1.20.1"]\n')
        (self.inputs / "1.20.1" / "java").mkdir(parents=True)
        # 目录只剩 26.3，1.20.1 应作为多余段被清掉
        added, ignored, _ = reconcile(self.root)

        text = (self.inputs / "manifest.toml").read_text(encoding="utf-8")
        self.assertEqual(ignored, [])
        self.assertIn('repo = "mc-src"', text)
        self.assertIn('["26.3"]', text)

    def test_reconcile_leaves_aligned_file_alone(self) -> None:
        body = '["26.3"]\n# 手写注释\n"java_home" = "/opt/jdk"\n'
        self._write(body)
        reconcile(self.root)
        self.assertEqual(
            (self.inputs / "manifest.toml").read_text(encoding="utf-8"), body
        )


if __name__ == "__main__":
    unittest.main()
