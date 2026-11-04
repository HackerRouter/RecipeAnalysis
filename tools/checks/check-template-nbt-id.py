"""统计模板的 cell 与方块身份。

`state` 是 `palette` 条目的引用，`nbt.id` 是方块实体身份。两者都按解析后的
`data` 计数：用子串计数会把 `final_state:` 算进 cell，也会把容器里的物品 id
当成方块实体 id。

默认读第一手模板（服务端 jar 内层的 `.nbt` 经 `--dev` 转出的 `.snbt`）；
传一个目录则统计该目录下的模板，例如被抹空的反编译源码树副本。
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from ra.adapters.templates import parse_snbt
from ra.inputs import ensure_structures, load_manifest
from ra.paths import cache_root, input_pack, repo_root


def resolve_root(label: str | None, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    root = repo_root()
    label = label or "26.3"
    structures = ensure_structures(load_manifest(input_pack(root, label)), cache_root(root))
    return structures.root / "data" / Path(structures.rel_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", help="模板根目录；省略则用第一手模板")
    parser.add_argument("--label", default=None, help="输入包标签，默认 26.3")
    args = parser.parse_args()

    files = sorted(resolve_root(args.label, args.root).rglob("*.snbt"))
    palette_items = 0
    palette_filled = 0
    readable = 0
    files_with_nbt_id = 0
    total_cells = 0
    cells_with_nbt_id = 0
    ids: Counter = Counter()

    for path in files:
        doc = parse_snbt(path.read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict):
            continue
        palette = doc.get("palette")
        if isinstance(palette, list):
            palette_items += len(palette)
            palette_filled += sum(1 for item in palette if isinstance(item, str) and item)

        data = doc.get("data")
        if not isinstance(data, list):
            continue
        total_cells += len(data)
        if any(
            isinstance(cell, dict)
            and isinstance(cell.get("state"), str)
            and cell["state"]
            for cell in data
        ):
            readable += 1

        found = [
            cell["nbt"]["id"]
            for cell in data
            if isinstance(cell, dict)
            and isinstance(cell.get("nbt"), dict)
            and isinstance(cell["nbt"].get("id"), str)
        ]
        if found:
            files_with_nbt_id += 1
            cells_with_nbt_id += len(found)
            ids.update(found)

    print(f"模板文件 {len(files)}")
    print(f"palette 项 {palette_items}   有值项 {palette_filled}")
    print(f"能从 state 读出方块的模板 {readable}")
    print(f"cell 总数 {total_cells}")
    print(f"带 nbt.id 的 cell {cells_with_nbt_id}   分布在 {files_with_nbt_id} 个文件")
    print("\nnbt.id 的取值分布（前 15）：")
    for name, count in ids.most_common(15):
        print(f"  {count:5d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
