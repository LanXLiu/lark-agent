"""飞书原生 markdown 清洗：把 /docs/v1/content 返回的 markdown 整理成切片友好的格式。

飞书返回的 markdown 有两个问题：
1. 标点被反斜杠 + HTML 实体双重转义（如 \\&\\#34; 实为 "），需还原；
2. 表格用 <table><tr><td> HTML 标签，需转成标准 markdown 表格 | a | b |。

清洗后标题是规范 #、表格是 | |，切片器能正确识别层级（breadcrumb）且表格不被逐行切碎。
"""

from __future__ import annotations

import html
import re

# 飞书会把这些标点反斜杠转义：\+ \& \# 等，反转义回来
_UNESCAPE_RE = re.compile(r"\\([+\-*_#`&>\[\]()!.~|{}])")


def clean_lark_markdown(text: str) -> str:
    """把飞书原生 markdown 清洗成切片友好的规范 markdown。"""
    text = _html_table_to_md(text)
    text = _unescape(text)
    return text


def _unescape(text: str) -> str:
    # 飞书是双重转义（先反斜杠 \&\#34; → &#34; → "），必须先去反斜杠再 html.unescape。
    text = _UNESCAPE_RE.sub(r"\1", text)
    for _ in range(3):  # HTML 实体可能多重，循环解到稳定
        new = html.unescape(text)
        if new == text:
            break
        text = new
    return text


def _html_table_to_md(text: str) -> str:
    def conv(m: re.Match) -> str:
        rows = re.findall(r"<tr>(.*?)</tr>", m.group(0), re.S)
        md_rows: list[str] = []
        for i, row in enumerate(rows):
            cells = re.findall(r"<td>(.*?)</td>", row, re.S)
            cells = [re.sub(r"\s+", " ", html.unescape(c)).strip() for c in cells]
            md_rows.append("| " + " | ".join(cells) + " |")
            if i == 0:
                md_rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
        return "\n".join(md_rows)

    return re.sub(r"<table>.*?</table>", conv, text, flags=re.S)
