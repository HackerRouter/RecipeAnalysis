"""输入层：装配、校验、provenance。

输入由使用方提供：一个 javap 源码树、一个数据包、一个服务端 jar。
reports 与结构模板由 jar 跑出来，不需要人工准备。
"""

from .data import DataSource, ensure_data
from .datagen import DatagenResult, run_datagen
from .java import JavaRuntime, probe_version, resolve_java
from .jar import JarInfo, classpath, extract_bundler, inspect_jar
from .manifest import Manifest, check_pack_layout, load_manifest, reconcile
from .reports import ReportsSource, ensure_reports
from .source import SourceTree, ensure_source, find_source_path, find_source_paths
from .structures import StructuresSource, ensure_structures

__all__ = [
    "DataSource",
    "DatagenResult",
    "JarInfo",
    "JavaRuntime",
    "Manifest",
    "ReportsSource",
    "SourceTree",
    "StructuresSource",
    "check_pack_layout",
    "classpath",
    "ensure_data",
    "ensure_reports",
    "ensure_source",
    "ensure_structures",
    "extract_bundler",
    "find_source_path",
    "find_source_paths",
    "inspect_jar",
    "load_manifest",
    "probe_version",
    "reconcile",
    "resolve_java",
    "run_datagen",
]
