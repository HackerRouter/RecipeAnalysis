"""把 `PathGraph` 渲染成 DOT / SVG / HTML。

## 为什么是 Graphviz

布局质量是这类图的主要成本。`dot` 的分层布局对「来源 → 产物」这种有向无环
结构几乎是现成答案，而前端布局库（dagre / cytoscape）在几百节点上明显更差。
代价是要装 Graphviz 二进制，所以 `dot` 缺失时必须给出可操作的一句话。

## 各形状的含义

写代码时的速查表。给读者看的那份是 `_LEGEND`（会被写进 HTML），两份要同步改：
这里漏一种形状，读者就会看到一个没有解释的符号。

| 形状 | 对应的节点 `sort` | 含义 |
|---|---|---|
| ◆ 菱形 | `rule` | 一条规则。指向它的箭头是**并列前提**，缺一不可 |
| ▤ folder（蓝） | `group` | 一组同类来源，组内每条各自有前提 |
| ▤ folder（灰） | `bucket` | 叶子桶（`merge_leaves`）：同一层 N 条并列来源 |
| □ 矩形 | `item` / `block` / `table` / `tag` … | 一个节点 |
| ○ 椭圆 | `assume` / `world` | 分析起点 |
| 便签 | `template` / `omitted` / `blocked` | 模板出处、受预算限制未展开、走不通 |
| 虚线无箭头 | `graph.dashed` | 附加信息，不是获取前提 |
| 虚线带箭头 | `graph.condition_edges` | 条件（设备 / 工具 / 附魔）：不给东西，只限条件 |
| 紫边 | `ISOMORPHIC_COLOR` | 同构簇聚合：一批只差原料的同类规则合成一条 |
| 红虚线便签 | `blocked` | 走不通的途径：body 含 FALSE / UNKNOWN，报数但不画边 |

## 输出格式

只出 `.dot` / `.svg` / `.html`：SVG 是矢量，覆盖拖动、缩放与打印；位图是
体积远大于它的额外副本（取舍见
`docs/adr/0009-report-artifacts.md`）。

## HTML 为什么不缩放 SVG

图宽度动辄三千点，缩到窗口宽会让字糊掉。保留原始尺寸，让外层容器滚动——
SVG 是矢量，放大看不会失真。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from html import escape as html_escape
from pathlib import Path

from .graph import PathGraph
from .options import PathOptions
from .style import DEFAULT_EDGE_COLOR, FILL, TARGET_BORDER, TARGET_FILL, short
from .summary import fold_notes


@dataclass(frozen=True)
class RenderResult:
    """一次渲染的产物路径与摘要。"""

    dot: Path
    svg: Path
    html: Path
    node_count: int
    edge_count: int
    rule_count: int
    merged_count: int
    group_count: int
    bucket_count: int
    omitted_count: int
    blocked_count: int
    folded_tags: int
    folded_conditions: int
    condition_leaves: int
    absorbed_assumptions: int
    absorbed_roots: int
    isomorphic_clusters: int
    isomorphic_rules: int
    absorbed_members: int
    collapsed_tables: int


def graphviz_available() -> bool:
    """`dot` 在不在 PATH 上。缺失是最常见的环境问题，先单独判。"""
    try:
        subprocess.run(["dot", "-V"], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def build_dot(graph: PathGraph, options: PathOptions) -> str:
    """`PathGraph` → DOT 文本。

    不写图内标题。参数与计数由 HTML 的文字区承担：图内标题在放大的图里会
    跟着缩成一条细线，而它恰恰是最需要看清的部分。
    """
    lines = [
        "digraph sources {",
        f"  rankdir={options.rankdir};",
        "  nodesep=0.20; ranksep=0.60;",
        "  bgcolor=white;",
        '  node [shape=box, style="filled,rounded", fontname="Microsoft YaHei",'
        ' fontsize=11, penwidth=0.8, margin="0.12,0.05"];',
        '  edge [fontname="Microsoft YaHei", fontsize=9, arrowsize=0.6, penwidth=1.2];',
    ]

    for key, info in graph.nodes.items():
        sort = info.get("sort", "item")

        if sort == "rule":
            # 规则节点用菱形：它代表「一条规则的全部前置」这个 AND 组。
            # 标签常有两三行（类别 / 工具 / 附魔），而菱形的文字矩形必须完全
            # 内切于斜边，所以 margin 要比其它节点大得多，否则文字会压到斜线上。
            lines.append(
                f'  "{key}" [shape=diamond, fillcolor="{FILL["rule"]}",'
                f' color="#94a3b8", label="{info["label"]}", fontsize=9,'
                f' margin="0.20,0.10", fontcolor="#334155",'
                f' tooltip="{_attr(info["tooltip"])}"];'
            )
            continue

        if sort == "group":
            # 聚合组用 folder：一个节点代表 N 条同类来源
            lines.append(
                f'  "{key}" [shape=folder, style="filled",'
                f' fillcolor="{FILL["group"]}", color="#6366f1",'
                f' fontcolor="#3730a3", fontsize=10, label="{info["label"]}",'
                f' tooltip="{_attr(info["tooltip"])}"];'
            )
            continue

        if sort == "bucket":
            # 叶子桶用 folder 但换色：它代表「同一类来源的 N 条并列记录」，
            # 不是「N 条同类规则」
            lines.append(
                f'  "{key}" [shape=folder, style="filled",'
                f' fillcolor="{FILL["bucket"]}", color="#94a3b8",'
                f' fontcolor="#334155", fontsize=10, label="{info["label"]}",'
                f' tooltip="{_attr(info["tooltip"])}"];'
            )
            continue

        if sort == "omitted":
            lines.append(
                f'  "{key}" [shape=note, style="dashed,filled",'
                f' fillcolor="{FILL["omitted"]}", color="#fb923c",'
                f' fontcolor="#9a3412", label="{info["label"]}"];'
            )
            continue

        if sort == "blocked":
            # 走不通的途径：红虚线便签。它不是来源，是「这里还有别的路」的提示
            lines.append(
                f'  "{key}" [shape=note, style="dashed,filled",'
                f' fillcolor="#fef2f2", color="#dc2626",'
                f' fontcolor="#991b1b", fontsize=9, label="{info["label"]}",'
                f' tooltip="{_attr(info["tooltip"])}"];'
            )
            continue

        # 用 dict 而不是 list：目标高亮要覆盖 root / leaf / cut 的样式，
        # list 里重复的属性键虽然 Graphviz 也认（取最后一次），但 `.dot`
        # 是给人读的，同一个属性出现两次会让人怀疑哪一个是生效的。
        attrs: dict[str, str] = {
            "label": f'"{info.get("label") or short(key)}"',
            "fillcolor": f'"{FILL.get(sort, "#f8fafc")}"',
            "tooltip": f'"{_attr(key)}"',
        }
        if sort == "template":
            attrs["shape"] = "note"
        if info.get("root"):
            attrs.update(shape="ellipse", penwidth="1.8", color='"#334155"')
        if info.get("leaf"):
            attrs["color"] = '"#0f766e"'
        if info.get("cut"):
            attrs.update(style='"dashed,filled"', color='"#94a3b8"')
        if key == graph.target:
            # 目标最后写，压过上面的 root / leaf / cut。目标同时是起点或
            # 叶子时，「这是本图的主角」比「它是哪种节点」更该被看见。
            #
            # 加粗 + 双层边框 + 换色，三个通道一起标：只换色的话，色觉差异
            # 与黑白打印两种情况都区分不出来。
            attrs.update(
                fillcolor=f'"{TARGET_FILL}"',
                color=f'"{TARGET_BORDER}"',
                penwidth="2.4",
                peripheries="2",
                fontsize="13",
                fontcolor='"#78350f"',
            )
        lines.append(
            f'  "{key}" [{", ".join(f"{k}={v}" for k, v in attrs.items())}];'
        )

    for (source, target, tag), (label, tooltip) in sorted(graph.edges.items()):
        color = graph.edge_colors.get((source, target, tag), DEFAULT_EDGE_COLOR)
        extra = ""
        if (source, target, tag) in graph.dashed:
            extra = ", style=dashed, arrowhead=none"
        elif (source, target, tag) in graph.condition_edges:
            # 条件是 AND 的一员，箭头保留；虚线 + 独立颜色表示「它不给东西」
            extra = ", style=dashed"
        if label == "（环）":
            # 环边是结构事实（合成 ↔ 分解），不是获取途径，画弱一点
            extra = ", style=dashed"
        lines.append(
            f'  "{source}" -> "{target}" [label="{label}", color="{color}",'
            f' fontcolor="{color}", tooltip="{_attr(tooltip)}"{extra}];'
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


def _attr(text: str) -> str:
    """DOT 属性值转义。双引号会提前结束属性，换行在 DOT 里必须是 `\\n`。"""
    return text.replace('"', "'").replace("\n", "\\n")


_LEGEND = """
  <b>▣ 琥珀色双框</b> = <b>本图的目标物品</b>：其余节点都是它的来源。
  用换色 + 双层边框 + 加粗三重标记，黑白打印或色觉差异下仍能区分。<br>
  <b>◆ 菱形</b> = 一条规则：指向它的箭头都是同一条获取路径的<b>并列前提</b>，缺一不可。
  只有<b>多个前置</b>时才画菱形；单前件规则直接压成边，标签写在箭头旁。<br>
  <b>▤ 蓝 folder</b> = 一组同类来源（如「村民交易 · 87 条」），组内每条各自有前置，默认不铺开。<br>
  <b>▤ 灰 folder</b> = 叶子桶（<code>--merge-leaves</code>）：同一层里 N 条并列来源
  （如「方块 · 13 条挖方块」）合一个，逐个明细在 tooltip 里。<br>
  <b>□ 矩形</b> = 一个节点（物品 / 方块 / 战利品表 / 标签 / 附魔）。
  同一产物被多个菱形或 folder 指向，就是多条<b>并列途径</b>。<br>
  <b>○ 椭圆</b> = 分析起点（<code>assume</code> / <code>world</code>），
  只在该起点仍有分支时出现；唯一来源是起点的节点已把起点写进标签第二行
  （如「草方块 / 主世界生成」），加 <code>--keep-roots</code> 可恢复成独立节点；<br>
  <b>便签</b> = 结构模板文件，或受预算限制未展开的来源；
  <b>虚线无箭头</b> = 附加信息（如模板出处），不是获取前提。<br>
  <b>条件</b>（设备 / 工具 / 附魔）不提供产物，已写进菱形标签的第二行，
  不计入上游层数；加 <code>--expand-conditions</code> 才拆成节点。<br>
  <b>紫色边</b> = 同构簇聚合：一批只差原料的同类规则合成一条，
  标签里的「N 组一一对应」是数量，配对表在 tooltip 里。
  折叠后成员的整层（每个树种的日志、原木与方块表）会上交给聚合节点，
  节点标签的「N 种」就是这一层被盖住的叶子数。<br>
  <b>红色便签</b> = 走不通的途径：这些规则的 body 含 <code>FALSE</code> / <code>UNKNOWN</code>，
  <b>图上不画边</b>（否则几十条死分支会挤走活分支），只报数与主要缺项，明细在 tooltip 里。
"""


def render_html(svg_text: str, value: str, graph: PathGraph, options: PathOptions) -> str:
    """把内联 SVG 包成可滚动的页面，并写清这一版图折叠了什么。"""
    svg = svg_text[svg_text.index("<svg"):]

    used_sorts = sorted(
        {i.get("sort", "item") for i in graph.nodes.values()}
        - {"rule", "group", "bucket", "omitted", "blocked"}
    )
    legend = " ".join(
        f'<span class="chip" style="background:{FILL.get(s, "#f8fafc")}">{s}</span>'
        for s in used_sorts
    )

    omitted = sum(graph.omitted.values())
    warn = (
        f'<div class="warn">有 {omitted} 条来源未展开'
        f"（<code>--max-groups {options.max_groups}</code> 或 "
        f"<code>--branches {options.branches}</code>），"
        f"图上以橙色便签标出——它们不是不存在。</div>"
        if omitted
        else ""
    )
    blocked_total = sum(graph.blocked.values())
    blocked_note = (
        f'<div class="warn blocked">有 {blocked_total} 条途径<b>走不通</b>'
        f"（body 含 <code>FALSE</code> / <code>UNKNOWN</code>），涉及 "
        f"{len(graph.blocked)} 个节点，图上以红色便签报数、不画边。"
        f"明细（每条规则的缺项）在便签 tooltip 里。</div>"
        if blocked_total
        else ""
    )

    folded = fold_notes(graph, options)
    fold_note = (
        f'<div class="warn info">已折叠：{"、".join(folded)}。'
        f"加 <code>--expand-tags</code> / <code>--expand-conditions</code> 可展开。</div>"
        if folded
        else ""
    )

    groups = len(graph.groups)
    group_note = (
        f"其中 {groups} 个是聚合组（folder），代表 "
        f"{sum(graph.groups.values())} 条同类来源，加 <code>--expand-groups</code> 看组内规则。"
        if groups
        else ""
    )

    # 每个参数一格。全量列出 13 项，单列会把文字区拉得很高，
    # 网格让它们在宽屏下自动排成多列。已转义：`--` 本身安全，
    # 但值里出现 `<` 时不能直接进 HTML。
    param_cells = "".join(
        f'<span>{html_escape(line)}</span>' for line in options.describe()
    )

    return f"""<!doctype html>
<html lang="zh"><meta charset="utf-8">
<title>{value} 的来源</title>
<style>
  body {{ margin:0; padding:20px 24px; font-family:"Microsoft YaHei",system-ui,sans-serif;
         background:#f8fafc; color:#0f172a; }}
  h1 {{ font-size:20px; margin:0 0 4px; font-weight:600; }}
  .sub {{ color:#64748b; font-size:13px; margin-bottom:12px; line-height:1.7; }}
  .warn {{ background:#fff7ed; border:1px solid #fdba74; color:#9a3412;
           border-radius:8px; padding:8px 12px; font-size:13px; margin-bottom:10px; }}
  .warn.info {{ background:#eef2ff; border-color:#a5b4fc; color:#3730a3; }}
  .warn.blocked {{ background:#fef2f2; border-color:#fca5a5; color:#991b1b; }}
  .label {{ font-size:12px; color:#64748b; margin:10px 0 4px; }}
  .chip {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
           border:1px solid #cbd5e1; margin:0 6px 6px 0; }}
  .notes {{ font-size:12.5px; color:#475569; line-height:1.8; }}
  .params {{ background:#fff; border:1px solid #e2e8f0; border-radius:8px;
             padding:8px 12px; font-size:12.5px; color:#475569;
             font-family:"Cascadia Mono",Consolas,monospace;
             display:grid; gap:2px 20px;
             grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); }}
  .graph {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px;
            padding:12px; margin-top:12px; overflow:auto; }}
</style>
<h1>{value}</h1>
<div class="sub">{len(graph.nodes)} 个图形节点、{len(graph.rules)} 个规则菱形、
{len(graph.merged)} 条单前件规则已合并进边、{len(graph.edges)} 条边。
箭头一律指「来源 → 产物」，从下往上读是一条获取路径。
{group_note}</div>
{warn}
{blocked_note}
{fold_note}
<div class="label">生成参数</div>
<div class="params">{param_cells}</div>
<div class="notes">{_LEGEND}</div>
<div class="label">节点排序</div>
<div>{legend}</div>
<div class="graph">{svg}</div>
</html>
"""


def write_outputs(
    graph: PathGraph,
    value: str,
    options: PathOptions,
    out_dir: Path,
    *,
    stem: str,
    counts: dict[str, int] | None = None,
) -> RenderResult:
    """写 `.dot/.svg/.html` 三个文件。

    SVG 用 `check=True`：它失败说明 DOT 有语法错，是必须知道的。
    不导出 PNG（见模块文档）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = counts or {}
    dot_file = out_dir / f"{stem}.dot"
    svg_file = out_dir / f"{stem}.svg"
    html_file = out_dir / f"{stem}.html"

    dot_file.write_text(build_dot(graph, options), encoding="utf-8", newline="\n")
    subprocess.run(["dot", "-Tsvg", "-o", str(svg_file), str(dot_file)], check=True)
    html_file.write_text(
        render_html(svg_file.read_text(encoding="utf-8"), value, graph, options),
        encoding="utf-8",
        newline="\n",
    )

    return RenderResult(
        dot=dot_file,
        svg=svg_file,
        html=html_file,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        rule_count=len(graph.rules),
        merged_count=len(graph.merged),
        group_count=len(graph.groups),
        bucket_count=graph.buckets,
        omitted_count=sum(graph.omitted.values()),
        blocked_count=sum(graph.blocked.values()),
        folded_tags=graph.folded_tags,
        folded_conditions=graph.folded_conditions,
        condition_leaves=graph.condition_leaves,
        absorbed_assumptions=graph.absorbed_assumptions,
        absorbed_roots=counts.get("absorbed_roots", 0),
        isomorphic_clusters=counts.get("isomorphic_clusters", 0),
        isomorphic_rules=graph.isomorphic,
        absorbed_members=graph.absorbed_members,
        collapsed_tables=counts.get("collapsed_tables", 0),
    )
