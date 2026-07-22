"""CLI：``python -m cleans <markdown_file> [flags]``

把一份 Markdown 跑一遍清洗，把结果写到 ``<file>.cleaned.md``，
并把命中的清洗类型 / 数量打印到 stderr，便于本地肉眼对比。

用法::

    # 默认全开
    python -m cleans path/to/output.md

    # 关掉某些步骤
    python -m cleans path/to/output.md --no-boilerplate --no-toc

    # 改阈值（更激进 / 更保守）
    python -m cleans path/to/output.md --hf-threshold=0.4 --hf-short-line-max=40

    # 不写文件，只打印 metadata
    python -m cleans path/to/output.md --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import MarkdownCleaner


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cleans",
        description="对 Markdown 文件跑一遍 KB-oriented 清洗管线",
    )
    p.add_argument("path", help="要清洗的 .md 文件路径")
    p.add_argument("--dry-run", action="store_true", help="只打印 metadata，不写文件")
    p.add_argument("--no-header-footer", action="store_true")
    p.add_argument("--no-page-number", action="store_true")
    p.add_argument("--no-toc", action="store_true")
    p.add_argument("--no-closing", action="store_true", help="关闭 thanks/Q&A/完 收尾行清洗")
    p.add_argument("--no-decoration", action="store_true")
    p.add_argument("--no-empty-blocks", action="store_true")
    p.add_argument("--no-duplicates", action="store_true", help="关闭整段精确去重")
    p.add_argument("--no-boilerplate", action="store_true")
    p.add_argument("--hf-threshold", type=float, default=0.5)
    p.add_argument("--hf-short-line-max", type=int, default=30)
    p.add_argument("--toc-min-consecutive", type=int, default=3)
    p.add_argument("--boilerplate-tail-paragraphs", type=int, default=5)
    p.add_argument("--dup-min-chars", type=int, default=20)
    p.add_argument("--dup-min-occurrences", type=int, default=2)
    p.add_argument(
        "--out",
        default=None,
        help="输出路径（默认 <path>.cleaned.md）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    src = Path(args.path).expanduser().resolve()
    if not src.is_file():
        print(f"❌ 文件不存在：{src}", file=sys.stderr)
        return 1

    raw = src.read_text(encoding="utf-8")

    cleaner = MarkdownCleaner(
        remove_headers_footers=not args.no_header_footer,
        remove_page_numbers=not args.no_page_number,
        remove_toc=not args.no_toc,
        remove_closing=not args.no_closing,
        remove_decoration=not args.no_decoration,
        remove_empty_blocks=not args.no_empty_blocks,
        remove_duplicates=not args.no_duplicates,
        remove_boilerplate=not args.no_boilerplate,
        header_footer_threshold=args.hf_threshold,
        header_footer_short_line_max=args.hf_short_line_max,
        toc_min_consecutive=args.toc_min_consecutive,
        boilerplate_tail_paragraphs=args.boilerplate_tail_paragraphs,
        duplicate_min_chars=args.dup_min_chars,
        duplicate_min_occurrences=args.dup_min_occurrences,
    )
    result = cleaner.clean(raw)

    print("---- cleaning metadata ----", file=sys.stderr)
    print(json.dumps(result.metadata, ensure_ascii=False, indent=2), file=sys.stderr)
    print(
        f"---- size: {len(raw)} -> {len(result.text)} "
        f"(Δ={len(raw) - len(result.text)} chars)",
        file=sys.stderr,
    )

    if args.dry_run:
        return 0

    out_path = Path(args.out) if args.out else src.with_suffix(".cleaned.md")
    out_path.write_text(result.text, encoding="utf-8")
    print(f"✔ 写入：{out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
