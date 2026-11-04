"""`ra-paths` 的命令行入口：读一份内部表示，出一份视图。

为什么可视化是独立命令、与 `ra graph` 怎么分工、依赖上的取舍，见
`docs/adr/0009-report-artifacts.md`。本模块只做参数解析
与「读 `graph.json` → 建图 → 渲染」的编排，不碰 `inputs/`，不重算规则与不动点。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ...errors import RaError
from ...ir.nodes import SORTS
from ...paths import repo_root
from . import PathBuildError, PathOptions, build_path_graph, resolve_node
from .options import PARAMS
from .render import graphviz_available, write_outputs
from .store import GraphFormatError, read_graph
from .summary import fold_notes


def cmd_render(args: argparse.Namespace) -> int:
    """从内部表示里取一个物品的来源，画成 `.dot/.svg/.html`。

    与 `ra why` 的分工：`why` 出树（一个节点只占一个位置，AND 组会被拆到不同
    层级），这里出图（AND 汇进菱形、OR 并列、条件分离）。
    """
    if not graphviz_available():
        print(
            "错误：找不到 Graphviz 的 dot。装好后确认在 PATH 上"
            "（Windows: https://graphviz.org/download/，Linux: apt install graphviz）。",
            file=sys.stderr,
        )
        return 1

    graph_path = Path(args.graph)
    if not graph_path.is_absolute():
        graph_path = (repo_root() / args.graph).resolve()

    try:
        rule_set, result, header = read_graph(graph_path)
    except GraphFormatError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    options = PathOptions(
        depth=args.depth,
        branches=args.branches,
        max_nodes=args.max_nodes,
        max_groups=args.max_groups,
        group_min=args.group_min,
        expand_tags=args.expand_tags,
        expand_conditions=args.expand_conditions,
        expand_groups=args.expand_groups,
        merge_isomorphic=args.merge_isomorphic,
        merge_leaves=args.merge_leaves,
        keep_tables=args.keep_tables,
        keep_roots=args.keep_roots,
        rankdir=args.rankdir,
    )

    value = resolve_node(args.node, SORTS)
    state = result.of(value)
    if state.name != "TRUE":
        print(f"{value} 不是 TRUE（{state.value}），没有可画的来源", file=sys.stderr)
        if state.name == "FALSE":
            print(
                f"用 `ra why --label {header.label} {args.node}` 看归因",
                file=sys.stderr,
            )
        return 1

    try:
        built = build_path_graph(rule_set, result, value, options)
    except PathBuildError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    # 与内部表示放同一目录：一份数据 + 它派生出的图。
    # label 里的点必须换成下划线：`Path.with_suffix` 会把 `.3_lectern` 当成后缀吃掉。
    stem = (
        f"paths_{header.label.replace('.', '_')}_"
        f"{args.node.split(':')[-1].replace('/', '_')}"
    )
    rendered = write_outputs(
        built.graph,
        value,
        options,
        graph_path.parent,
        stem=stem,
        counts={
            "isomorphic_clusters": built.isomorphic_clusters,
            "collapsed_tables": built.collapsed_tables,
            "absorbed_roots": built.absorbed_roots,
        },
    )

    print(
        f"图形节点 {rendered.node_count}"
        f"（菱形 {rendered.rule_count}、聚合组 {rendered.group_count}、"
        f"合并进边的单前件规则 {rendered.merged_count}）  边 {rendered.edge_count}"
    )
    if built.truncated_at:
        print(
            f"警告：节点数超过 {options.max_nodes}（在 {built.truncated_at} 处截断）；"
            f"用 --branches 调小或 --max-nodes 调大",
            file=sys.stderr,
        )
    _print_folds(built.graph, options)
    if rendered.omitted_count:
        print(f"未展开 {rendered.omitted_count} 条（受 --max-groups / --branches 限制）")
    if rendered.blocked_count:
        print(
            f"走不通 {rendered.blocked_count} 条（涉及 {len(built.graph.blocked)} 个节点，"
            f"body 含 FALSE / UNKNOWN；图上红便签报数）"
        )
    print(f" -> {rendered.svg}")
    print(f" -> {rendered.html}")
    return 0


def _print_folds(graph, options) -> None:
    """把这一版图做了哪些折叠逐条写出来。

    折叠是默认可读性取舍，不是删数据。不写出来的话，读者会以为图上就是全部。
    措辞与 HTML 提示共用 `summary.fold_notes`——两处各写一份就会漂。
    """
    for note in fold_notes(graph, options):
        print(note)


def _add_path_options(parser: argparse.ArgumentParser) -> None:
    """按 `options.PARAMS` 生成参数，与 HTML 的参数表同源（`describe()`）。"""
    for param in PARAMS:
        kwargs: dict[str, object] = {"help": param.help}
        if param.metavar:
            kwargs["metavar"] = param.metavar
        if param.choices:
            kwargs["choices"] = list(param.choices)
        if isinstance(param.default, bool):
            parser.add_argument(param.flag, action="store_true", **kwargs)
        else:
            parser.add_argument(
                param.flag, type=type(param.default), default=param.default, **kwargs
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ra-paths",
        description="把物品的来源画成图（Graphviz）。读 `ra graph` 写的内部表示，不碰输入包。",
    )
    parser.add_argument(
        "--graph",
        required=True,
        help="内部表示文件（`ra graph` 的产物，如 output/<label>/graph.json）；"
        "相对路径按仓库根解析",
    )
    parser.add_argument("node", help="物品 id，如 minecraft:cod_bucket 或 item:minecraft:planks")
    _add_path_options(parser)
    parser.set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RaError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
