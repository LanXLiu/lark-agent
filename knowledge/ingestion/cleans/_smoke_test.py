"""现场冒烟测试：覆盖每条清洗规则各 1 个典型样本。

不是单元测试框架，直接 ``python -m knowledge.ingestion.cleans._smoke_test`` 就能跑。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_EMPTY_HEADING_RE = re.compile(r"^#{1,6}\s*$", re.MULTILINE)

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from knowledge.ingestion.cleans import (  # noqa: E402
    clean_markdown,
    is_closing_line,
    is_decoration_line,
    is_page_number_line,
    is_toc_line,
)


def _ok(cond: bool, label: str) -> None:
    print(("✔ " if cond else "✘ ") + label)
    if not cond:
        sys.exit(1)


def test_unit_predicates() -> None:
    print("\n== unit predicates ==")
    _ok(is_page_number_line("第 12 页"), "page_number 中文 `第 12 页`")
    _ok(is_page_number_line("12 / 28"), "page_number `12 / 28`")
    _ok(is_page_number_line("Page 3 of 28"), "page_number `Page 3 of 28`")
    _ok(is_page_number_line("- 7 -"), "page_number `- 7 -`")
    _ok(not is_page_number_line("## Page 1"), "不误删 `## Page 1` 标题行")
    _ok(not is_page_number_line("普通正文 12"), "不误删 `普通正文 12`")

    _ok(is_decoration_line("---"), "decoration `---`")
    _ok(is_decoration_line("═══════════"), "decoration `═══` 全角")
    _ok(is_decoration_line("———————"), "decoration `———` 破折号")
    _ok(not is_decoration_line("正文 ---"), "不误删 `正文 ---`")

    _ok(is_toc_line("第一章 概述 ............... 1"), "toc `第一章 ... 1`")
    _ok(is_toc_line("Chapter 1 .......... 5"), "toc 英文")
    _ok(not is_toc_line("hello world"), "不误删 `hello world`")

    _ok(is_closing_line("THANK YOU !"), "closing `THANK YOU !`")
    _ok(is_closing_line("Thank you"), "closing `Thank you`")
    _ok(is_closing_line("## 谢谢"), "closing `## 谢谢` 标题形态")
    _ok(is_closing_line("谢谢大家"), "closing `谢谢大家`")
    _ok(is_closing_line("感谢您的聆听"), "closing `感谢您的聆听`")
    _ok(is_closing_line("感谢您的 聆听"), "closing `感谢您的 聆听`（容忍空格）")
    _ok(is_closing_line("Q&A"), "closing `Q&A`")
    _ok(is_closing_line("**THANK YOU!**"), "closing 带 markdown 强调 `**THANK YOU!**`")
    _ok(is_closing_line("完"), "closing `完`")
    _ok(
        not is_closing_line("感谢您对项目落地一直以来的鼎力相助"),
        "不误删长正文（白名单外字符如 `项目落地一鼎力相助`）",
    )
    _ok(not is_closing_line("致谢部分写明了项目组成员"), "不误删 `致谢` 开头的正文")
    _ok(
        not is_closing_line("# 第一章 谢谢您的成就"),
        "不误删一级标题正文（含 `谢谢您` 但有非白名单字 `成就`）",
    )


def test_header_footer() -> None:
    print("\n== header / footer (≥3 pages, repeat ≥ 50%) ==")
    md = "\n".join(
        [
            "# title",
            "## sec1",
            "<!-- page: 1 -->",
            "",
            "公司机密文档",
            "正文 A",
            "",
            "## sec2",
            "<!-- page: 2 -->",
            "",
            "公司机密文档",
            "正文 B",
            "",
            "## sec3",
            "<!-- page: 3 -->",
            "",
            "公司机密文档",
            "正文 C",
            "",
        ]
    )
    r = clean_markdown(md, remove_boilerplate=False, remove_decoration=False)
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok("公司机密文档" not in r.text, "跨页重复短行 `公司机密文档` 已剔除")
    _ok("正文 A" in r.text and "正文 B" in r.text, "正文未被误删")
    _ok(r.metadata.get("removed_headers_footers"), "metadata.removed_headers_footers 有内容")


def test_page_numbers_and_toc_and_decoration() -> None:
    print("\n== page numbers + toc + decoration ==")
    md = "\n".join(
        [
            "# 文档",
            "",
            "## 目录",
            "",
            "第一章 概述 ............... 1",
            "第二章 服务 ............... 5",
            "第三章 流程 ............... 9",
            "",
            "## 第一章 概述",
            "正文若干",
            "",
            "------",
            "第 1 页",
            "",
            "## 第二章 服务",
            "更多正文",
            "",
            "═══════════",
            "Page 2",
            "",
        ]
    )
    r = clean_markdown(md, remove_boilerplate=False, remove_headers_footers=False)
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok(r.metadata.get("removed_toc_lines", 0) >= 3, "TOC ≥ 3 行被识别")
    _ok("toc" in r.metadata and len(r.metadata["toc"]) >= 3, "metadata.toc 保留了原始 TOC 行")
    _ok(r.metadata.get("removed_page_numbers", 0) >= 2, "页码 `第 1 页`/`Page 2` 被剔除")
    _ok(r.metadata.get("removed_decoration_lines", 0) >= 2, "装饰行 `---`/`═══` 被剔除")
    _ok("第一章 概述 ......" not in r.text, "目录正文已删")
    _ok("第 1 页" not in r.text, "页码行已删")
    _ok("═══════════" not in r.text, "全角分隔已删")


def test_empty_blocks_and_boilerplate() -> None:
    print("\n== empty blocks + boilerplate ==")
    md = "\n".join(
        [
            "# 文档",
            "",
            "正文 1",
            "",
            "##",
            "",
            "- ",
            "* ",
            "+",
            "",
            "正文 2",
            "",
            "## 附录",
            "",
            "更多正文 3",
            "",
            "版权所有 (C) 2024 某某公司。未经允许不得复制传播。",
            "",
        ]
    )
    r = clean_markdown(md, remove_headers_footers=False, remove_decoration=False)
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok(r.metadata.get("removed_empty_blocks", 0) >= 3, "空标题/空 bullet 被删")
    _ok(r.metadata.get("removed_boilerplate_paragraphs", 0) >= 1, "尾部版权声明被删")
    _ok(
        _EMPTY_HEADING_RE.search(r.text) is None,
        "空 `##`（仅 hash + 空白的标题行）不再存在",
    )
    _ok("## 附录" in r.text, "非空标题 `## 附录` 被正确保留")
    _ok("版权所有" not in r.text, "版权段已删")
    _ok("正文 1" in r.text and "正文 2" in r.text and "更多正文 3" in r.text, "正文均保留")


def test_list_style_toc() -> None:
    print("\n== list-style TOC (PPT 议程页) ==")
    md = "\n".join(
        [
            "# 文档",
            "",
            "## 目录",
            "<!-- page: 12 -->",
            "",
            "- 1 公司介绍",
            "- 2 需求理解",
            "- 3 WMS核心功能",
            "- 4 方案 - 基础配置",
            "",
            "## 第一章 公司介绍",
            "",
            "正文若干",
        ]
    )
    r = clean_markdown(md, remove_boilerplate=False, remove_headers_footers=False)
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok(
        r.metadata.get("removed_toc_lines", 0) >= 4,
        "列表式 TOC（heading + ≥3 list 项）被识别",
    )
    _ok("- 1 公司介绍" not in r.text, "TOC 列表项被删")
    _ok("## 目录" not in r.text, "TOC 标题被删")
    _ok("## 第一章 公司介绍" in r.text, "下一章节标题被保留")
    _ok("<!-- page: 12 -->" in r.text, "页标记保留作溯源")


def test_closing_thanks() -> None:
    print("\n== closing / thanks / Q&A ==")
    md = "\n".join(
        [
            "# 文档",
            "",
            "## 正文一",
            "内容 A",
            "",
            "## Q&A",
            "",
            "<!-- page: 30 -->",
            "",
            "## 谢谢",
            "",
            "感谢您的 聆听",
            "",
            "THANK YOU !",
            "",
        ]
    )
    r = clean_markdown(
        md,
        remove_boilerplate=False,
        remove_headers_footers=False,
        remove_decoration=False,
    )
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok(r.metadata.get("removed_closing_lines", 0) >= 4, "至少 4 条结束行被剔除")
    _ok("THANK YOU" not in r.text, "`THANK YOU` 已删")
    _ok("感谢您的" not in r.text, "`感谢您的 聆听` 已删")
    _ok("谢谢" not in r.text, "`## 谢谢` 已删")
    _ok("Q&A" not in r.text, "`## Q&A` 已删")
    _ok("内容 A" in r.text, "正文 `内容 A` 保留")


def test_duplicate_paragraphs() -> None:
    print("\n== duplicate paragraphs ==")
    repeated_block = "公司机密文档\n请勿外传\n版权所有 2024"
    md = "\n\n".join(
        [
            "# 文档",
            "## 第一章",
            "这是第一章的正文，长度足够参与去重判定。",
            repeated_block,
            "## 第二章",
            "这是第二章的正文，长度足够参与去重判定。",
            repeated_block,
            "## 第三章",
            "这是第三章的正文，长度足够参与去重判定。",
            repeated_block,
        ]
    )
    r = clean_markdown(
        md,
        remove_boilerplate=False,
        remove_headers_footers=False,
        remove_closing=False,
        remove_decoration=False,
    )
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok(r.metadata.get("removed_duplicate_paragraphs", 0) >= 2, "重复段被删 ≥2 次")
    _ok(r.text.count("公司机密文档") == 1, "重复段只保留首次出现")
    _ok("这是第一章的正文" in r.text, "正文未误删")
    _ok("这是第三章的正文" in r.text, "末段正文未误删")


def test_short_noise_lines() -> None:
    print("\n== short noise lines ==")
    md = "\n".join(
        [
            "# 文档标题",
            "（上）",
            "上",
            "## 项目背景",
            "- 短项",
            "状态：正常",
            "这是超过八个字的正文内容",
        ]
    )
    r = clean_markdown(
        md,
        remove_headers_footers=False,
        remove_page_numbers=False,
        remove_toc=False,
        remove_closing=False,
        remove_decoration=False,
        remove_empty_blocks=False,
        remove_duplicates=False,
        remove_boilerplate=False,
    )
    print("metadata =", json.dumps(r.metadata, ensure_ascii=False))
    _ok(r.metadata.get("removed_short_noise_lines") == 2, "极短中文噪声行删除 2 条")
    _ok("（上）" not in r.text and "\n上\n" not in f"\n{r.text}\n", "短噪声已删")
    _ok("## 项目背景" in r.text, "短标题保留")
    _ok("- 短项" in r.text, "短列表项保留")
    _ok("状态：正常" in r.text, "字段标签行保留")


def main() -> int:
    test_unit_predicates()
    test_header_footer()
    test_page_numbers_and_toc_and_decoration()
    test_list_style_toc()
    test_closing_thanks()
    test_duplicate_paragraphs()
    test_short_noise_lines()
    test_empty_blocks_and_boilerplate()
    print("\n🎉 全部 smoke test 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
