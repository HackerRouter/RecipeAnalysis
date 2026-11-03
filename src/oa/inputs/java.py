"""校验用户指定的 Java。

不做搜索：Java 是使用方要准备的环境，项目不猜它在哪。datagen 的类要求特定大版本，
用错会 `UnsupportedClassVersionError`，而搜索猜错比缺失更难查。

所需大版本来自 jar 内 `version.json`，这是唯一的事实源；指定路径在这一处校验。

缺配置时抛 `InputError`，流程停在数据导出，不降级、不回退到 PATH。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..errors import InputError

_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


@dataclass(frozen=True)
class JavaRuntime:
    path: Path
    version: int
    component: str

    def as_json(self) -> dict:
        return {"path": str(self.path), "version": self.version, "component": self.component}


def _java_exe(home: Path) -> Path:
    """`home` 可以是 JDK 根目录，也可以直接是 java 可执行文件。"""
    if home.is_file():
        return home
    for rel in ("bin/java.exe", "bin/java"):
        cand = home / rel
        if cand.is_file():
            return cand
    raise InputError(f"{home} 下没有 bin/java，也不是 java 可执行文件")


def probe_version(java: Path) -> int | None:
    try:
        proc = subprocess.run(
            [str(java), "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (proc.stderr or "") + (proc.stdout or "")
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    major = int(match.group(1))
    # 1.8 → 8；1.7 → 7
    if major == 1 and match.group(2):
        return int(match.group(2))
    return major


def resolve_java(
    java_home: Path | None,
    required_version: int | None,
    component: str | None,
    label: str,
) -> JavaRuntime:
    """校验 `manifest.toml` 给的 Java。

    `java_home` 缺失即报错并给出可照抄的下一步，不尝试自己找。
    """
    if java_home is None:
        required = f"Java {required_version}" if required_version is not None else "指定版本的 Java"
        raise InputError(
            f"输入包 {label} 未指定 Java，数据导出无法进行。\n"
            f"该版本的 jar 要求 {required}。\n"
            f'在 inputs/{label}/manifest.toml 的 [java] 段写 "home" = "<JDK 根目录>" 后重试。'
        )

    exe = _java_exe(java_home)
    version = probe_version(exe)
    if version is None:
        raise InputError(f"无法确定 {exe} 的 Java 版本，确认它是一个可用的 JDK")

    if required_version is not None and version != required_version:
        raise InputError(
            f"{exe} 是 Java {version}，输入包 {label} 的 jar 要求 Java {required_version}。\n"
            f'在 inputs/{label}/manifest.toml 里把 [java] 的 "home" 指向一个 Java {required_version} 的 JDK。'
        )

    return JavaRuntime(exe, version, component or "")
