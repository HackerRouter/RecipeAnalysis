"""把探测与产物结论渲染成某个版本的「适配指南」。

指南回答的是「在本次输入里，哪些位置有数据、各自是什么形状、哪些看着像但不能用」，
而不是「这个版本有多少个文件」。规模数字随输入变化，判据不随输入变化——判据写在
`docs/shapes.md`，本模块只负责把该版本的实测结论填进去，并指向对应判据。

本层只消费内存里的 dict，不读文件：调用方（`cli`）负责把 `output/<label>/` 下的
JSON 读进来。与 `report` 其余模块一致，出现文件访问即为分层失效。
"""

from __future__ import annotations

from typing import Any

SHAPES_DOC = "docs/shapes.md"

_UNKNOWN = "—"


def _cell(value: Any) -> str:
    if value is None or value == "":
        return _UNKNOWN
    return str(value)


def _path(value: Any, root: str | None) -> str | None:
    """归一化路径写法，且不把本机的用户目录写进产物。

    仓库内路径转相对；仓库外路径只保留最后一级作为身份——上游目录名属于使用方的
    机器信息，与复算无关。
    """
    if value is None or value == "":
        return None
    text = str(value).replace("\\", "/")
    if root:
        prefix = root.replace("\\", "/").rstrip("/")
        # 前缀必须落在目录边界上，否则 /work/repo 会吞掉 /work/repo-mirror
        if text == prefix or text.startswith(prefix + "/"):
            rel = text[len(prefix):].lstrip("/")
            return f"<REPO_ROOT>/{rel}" if rel else "<REPO_ROOT>"
    if ":/" in text or text.startswith("/"):
        parts = [p for p in text.split("/") if p]
        return f"…/{parts[-1]}" if parts else text
    return text


def _pct(value: Any) -> str:
    try:
        return f"{float(value):.0%}"
    except (TypeError, ValueError):
        return _UNKNOWN


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return out


def _section_provenance(profile: dict, root: str | None) -> list[str]:
    version = profile.get("version") or {}
    reports = profile.get("reports") or {}
    jar = profile.get("jar") or {}
    java = reports.get("java") or {}
    lines = ["## 版本与 provenance", ""]
    lines.extend(_table(["项", "值"], [
        ["标签", profile.get("label")],
        ["内容提交", profile.get("content_commit")],
        ["反编译源码仓", _path(profile.get("source_repo"), root)],
        ["`pack_version.data_major`", version.get("pack_data_major")],
        ["`world_version`", version.get("world_version")],
        ["`protocol_version`", version.get("protocol_version")],
        ["jar", jar.get("path")],
        ["jar `sha256`", jar.get("sha256")],
        ["Java 大版本", java.get("version")],
        ["Java 组件", java.get("component")],
    ]))
    lines.append("")
    if not profile.get("content_commit"):
        lines.append("> 未配置 `content_commit`，反编译源码的 provenance 记为 `null`，本报告不可复算代码侧结论。")
        lines.append("")
    return lines


def _describe_merge(merge: dict) -> str | None:
    """一行说清数据包覆盖是否生效。"""
    if merge.get("mode") != "merged":
        return "未启用（无 datapacks/ 输入）"
    packs = merge.get("packs") or []
    names = "、".join(str(pack.get("name")) for pack in packs)
    return (
        f"{names}：覆盖 {merge.get('overrides')} 处、"
        f"标签合并 {merge.get('tag_merges')} 处、filter 屏蔽 {merge.get('filtered')} 处"
    )


def _section_inputs(profile: dict, root: str | None) -> list[str]:
    reports = profile.get("reports") or {}
    lines = ["## 输入布局", ""]
    lines.extend(_table(["位置", "结论"], [
        ["reports", reports.get("kind")],
        ["reports 根", _path(reports.get("root"), root)],
        ["默认组件布局", reports.get("components_layout")],
        ["默认组件目录", _path(reports.get("components_dir"), root)],
        ["`datapack.json`", reports.get("datapack_capability")],
        ["`blocks.json`", reports.get("block_report")],
        ["生效数据根", _path(profile.get("data_root"), root)],
        ["数据包覆盖", _describe_merge(profile.get("datapack_merge") or {})],
        ["命名空间", "、".join(profile.get("namespaces") or []) or None],
    ]))
    lines.append("")
    lines.append("各项的取值与判据见 [`docs/shapes.md`](../../docs/shapes.md) 的「运行期导出」一节。")
    lines.append("")
    return lines


def _describe_formats(formats: object) -> str | None:
    """`{"min": [maj, min], "max": [...]}` → `100.0–121.0`。"""
    if not isinstance(formats, dict):
        return None
    low = formats.get("min")
    high = formats.get("max")
    if not (isinstance(low, list) and isinstance(high, list)):
        return None
    return f"{'.'.join(str(v) for v in low)}–{'.'.join(str(v) for v in high)}"


def _describe_overlays(pack: dict) -> str | None:
    overlays = pack.get("overlays") or []
    if not overlays:
        return None
    active = [item for item in overlays if item.get("applicable")]
    return f"{len(active)}/{len(overlays)} 适用"


def _section_datapacks(profile: dict, root: str | None) -> list[str]:
    """外来数据包：哪些包生效、按什么顺序、覆盖了多少。"""
    merge = profile.get("datapack_merge") or {}
    lines = ["## 数据包覆盖", ""]
    if merge.get("mode") != "merged":
        lines.extend(["本次输入没有外来数据包，生效数据根就是原版派生目录。", ""])
        return lines

    packs = merge.get("packs") or []
    lines.extend(_table(
        ["包", "形态", "格式范围", "data 文件", "overlay", "摘要"],
        [
            [
                pack.get("name"),
                pack.get("kind"),
                _describe_formats(pack.get("formats")),
                pack.get("data_files"),
                _describe_overlays(pack),
                (pack.get("digest") or "")[:12],
            ]
            for pack in packs
        ],
    ))
    lines.append("")
    lines.append(f"合并结果 {merge.get('files')} 个文件 → {_path(merge.get('root'), root)}")
    lines.append("")
    for note in merge.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("合并语义见 [`docs/shapes.md`](../../docs/shapes.md) 的「数据包覆盖」一节。")
    lines.append("")
    return lines


def _section_dirs(profile: dict) -> list[str]:
    dirs = profile.get("dirs") or {}
    lines = ["## 数据包目录归属", ""]
    if not dirs:
        lines.extend(["本次输入没有可归属的数据包注册表目录。", ""])
        return lines
    rows = []
    for name, claim in sorted(dirs.items()):
        rows.append([
            name,
            claim.get("path"),
            claim.get("files"),
            claim.get("shape"),
            _pct(claim.get("coverage")),
            claim.get("status"),
        ])
    lines.extend(_table(["注册表", "目录", "文件数", "形状", "归属覆盖率", "状态"], rows))
    lines.append("")
    lines.append(
        "目录归属按「注册表条目名与目录内容的交集」判定，不按目录名匹配，"
        "因此单复数两种形态由同一份探测代码吸收。"
        f"判据见 [数据形态指南]({'../../' + SHAPES_DOC}) 的「数据包目录归属」一节。"
    )
    lines.append("")
    return lines


def _section_tag_dirs(profile: dict) -> list[str]:
    tag_dirs = profile.get("tag_dirs") or {}
    lines = ["## 标签子目录归属", ""]
    if not tag_dirs:
        lines.extend(["本次输入没有可归属的标签子目录。", ""])
        return lines
    rows = [[reg, item.get("path"), item.get("files"), _pct(item.get("coverage")), item.get("status")]
            for reg, item in sorted(tag_dirs.items())]
    lines.extend(_table(["注册表", "目录", "文件数", "归属覆盖率", "状态"], rows))
    lines.append("")
    lines.append("标签 ID 不含注册表子目录，判据见 [数据形态指南](../../docs/shapes.md) 的「标签」一节。")
    lines.append("")
    return lines


def _section_templates(profile: dict, root: str | None) -> list[str]:
    tpl = profile.get("templates") or {}
    lines = ["## 结构模板", ""]
    lines.extend(_table(["项", "值"], [
        ["模板目录", tpl.get("dir")],
        ["扩展名", tpl.get("ext")],
        ["第一手来源", tpl.get("source")],
        ["解出根", _path(tpl.get("root"), root)],
        ["反编译源码树侧同路径", tpl.get("dir_src")],
        ["文件数", tpl.get("files")],
    ]))
    lines.append("")
    source = tpl.get("source")
    if source == "jar":
        lines.append("第一手取自服务端 jar 内层的二进制模板，反编译源码树侧的同名文件只作交叉校验。")
    elif source == "src":
        lines.append("jar 内层不可得，退回反编译源码树；该来源的 `palette` 可能被抹空，需核对有值项。")
    else:
        lines.append("未找到模板目录。")
    lines.append("")
    lines.append("模板目录按「目录下全为二进制模板」的形状判定，不按目录名。"
                 "两个来源必须分开记，判据见 [数据形态指南](../../docs/shapes.md) 的「结构模板」一节。")
    lines.append("")
    return lines


def _section_worldgen(profile: dict) -> list[str]:
    wg = profile.get("worldgen") or {}
    counts = wg.get("counts") or {}
    lines = ["## 世界生成", ""]
    lines.append(f"来源：`{_cell(wg.get('source'))}`")
    lines.append("")
    if counts:
        rows = [[k, v] for k, v in sorted(counts.items())]
        lines.extend(_table(["子目录", "条目数"], rows))
        lines.append("")
    lines.append("两侧来源互补：数据包侧与运行期导出侧通常只有一侧存在，"
                 "因此双路对账不必然触发。对账的不对称判据见 "
                 "[数据形态指南](../../docs/shapes.md) 的「世界生成」一节。")
    lines.append("")
    return lines


def _section_loot(profile: dict) -> list[str]:
    loot = profile.get("loot_dialect") or {}
    evidence = loot.get("evidence") or {}
    lines = ["## 战利品方言", ""]
    lines.append(f"方言：`{_cell(loot.get('dialect'))}`")
    if evidence:
        lines.append("")
        lines.append("证据计数：" + "、".join(f"{k} {v}" for k, v in sorted(evidence.items())))
    lines.append("")
    lines.append("方言按每个文件自身的形状判定，不按版本号。判据见 "
                 "[数据形态指南](../../docs/shapes.md) 的「战利品表」一节。")
    lines.append("")
    return lines


def _section_excluded(profile: dict) -> list[str]:
    excluded = profile.get("excluded_dirs") or []
    lines = ["## 整棵排除的目录", ""]
    if excluded:
        lines.extend(f"- `{item}`" for item in excluded)
        lines.append("")
        lines.append("这些目录的内容不属于原版，扫描时必须整棵排除。")
    else:
        lines.append("本次输入没有需要整棵排除的目录。")
    lines.append("")
    return lines


def _section_notes(profile: dict) -> list[str]:
    notes = profile.get("notes") or []
    lines = ["## 探测到但未归属的目录", ""]
    if not notes:
        lines.extend(["没有未归属的目录。", ""])
        return lines
    lines.append("下列目录被探测到，形状不明确或不属于任何已实现的族，"
                 "因此**不作为数据源**。新增适配器应从这里取候选。")
    lines.append("")
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")
    return lines


def _section_unresolved(profile: dict) -> list[str]:
    unresolved = profile.get("unresolved") or []
    lines = ["## 未决项", ""]
    if not unresolved:
        lines.extend(["无未决项。", ""])
        return lines
    for item in unresolved:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("存在未决项时 `ra probe --strict` 与 `ra ingest` 返回非零。")
    lines.append("")
    return lines


def _section_products(facts_summary: dict | None,
                      coverage: dict | None,
                      run: dict | None) -> list[str]:
    if not any((facts_summary, coverage, run)):
        return []
    lines = ["## 事实与规则产出", ""]

    if facts_summary:
        kinds = facts_summary.get("kinds") or {}
        status = facts_summary.get("status") or {}
        if kinds:
            lines.extend(_table(["事实种类", "条数"],
                                [[k, v] for k, v in sorted(kinds.items())]))
            lines.append("")
        if status:
            lines.append("状态分布：" + "、".join(f"`{k}` {v}" for k, v in sorted(status.items())))
            lines.append("")
        unavailable = facts_summary.get("unavailable_families") or []
        if unavailable:
            lines.append("族级不可用：")
            lines.append("")
            lines.extend(_table(["族", "原因", "说明"],
                                [[u.get("family"), u.get("reason"), u.get("note")]
                                 for u in unavailable]))
            lines.append("")
            lines.append("族级不可用由 `FactStore.mark_unavailable` 登记，不写台账，"
                         "否则覆盖率分母虚高。")
            lines.append("")

    if coverage:
        families = coverage.get("rule_families") or {}
        if families:
            lines.append("规则族：")
            lines.append("")
            lines.extend(_table(["族", "规则数"],
                                [[k, v] for k, v in sorted(families.items())]))
            lines.append("")
        nodes = coverage.get("nodes_by_sort") or {}
        if nodes:
            lines.append("节点按排序计数：" + "、".join(f"`{k}` {v}" for k, v in sorted(nodes.items())))
            lines.append("")

    if run:
        reach = run.get("reachability") or {}
        if reach:
            by_status = reach.get("by_status") or {}
            lines.extend(_table(["项", "值"], [
                ["分母（注册表全集）", reach.get("identities")],
                ["可达", by_status.get("true")],
                ["不可达", by_status.get("false")],
                ["可达率", _pct(reach.get("rate")) if reach.get("rate") is not None else None],
            ]))
            lines.append("")
    return lines


def _section_commands(label: str) -> list[str]:
    lines = ["## 复算", "", "```bash",
             f"ra probe   --label {label}",
             f"ra ingest  --label {label}",
             f"ra run     --label {label}",
             f"ra guide   --label {label}",
             "```", ""]
    lines.append("产物的字段与统计口径见 `output/<label>/` 根上的 `profile.json` 与 `facts/`、`report/` 下的同名 JSON。")
    lines.append("")
    return lines


def render_guide(*, profile: dict,
                 facts_summary: dict | None = None,
                 coverage: dict | None = None,
                 run: dict | None = None,
                 root: str | None = None) -> str:
    """渲染一个版本的适配指南。所有入参都是已读入的 dict。

    `root` 给出仓库根时，产物内的绝对路径会转为相对形式。
    """
    label = profile.get("label") or "<label>"
    lines = [
        f"# 适配指南：{label}",
        "",
        "本文件由 `ra guide` 从 `output/<label>/` 的产物生成，不入版本库。",
        "它记录本次输入的实测结论——哪些位置有数据、各自是什么形状、哪些探测到了但不能用。",
        f"识别方法与不可做的事属于跨版本判据，写在 [`{SHAPES_DOC}`](../../{SHAPES_DOC})，本文按节指向那里。",
        "",
    ]
    for part in (
        _section_provenance(profile, root),
        _section_inputs(profile, root),
        _section_datapacks(profile, root),
        _section_dirs(profile),
        _section_tag_dirs(profile),
        _section_templates(profile, root),
        _section_worldgen(profile),
        _section_loot(profile),
        _section_excluded(profile),
        _section_notes(profile),
        _section_unresolved(profile),
        _section_products(facts_summary, coverage, run),
        _section_commands(label),
    ):
        lines.extend(part)
    return "\n".join(lines).rstrip() + "\n"
