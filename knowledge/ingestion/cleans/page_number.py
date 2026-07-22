"""页码行剔除。

只删整行就是页码的：

- 纯页码：``  3  ``、``42``；
- 中文：``第 12 页``、``12 / 28``、``12/28``、``第 3 页 共 12 页``；
- 英文：``Page 3``、``Page 3 of 28``；
- 排版常见：``- 12 -``、``— 12 —``、``· 12 ·``。

注意
----
不会误删 ``## Page 12``（Markdown 标题行），因为页码 patterns 都要求**整行**只
含页码本身或纯数字；标题行有 ``#`` 前缀。
"""

from __future__ import annotations

import re

_PAGE_NUMBER_PATS: tuple[re.Pattern[str], ...] = (
    # 纯数字行（保守地限制 1~4 位，避免误伤）
    re.compile(r"^\s*\d{1,4}\s*$"),
    # 第 X 页 / 第 X 页 共 Y 页 / X / Y 页
    re.compile(r"^\s*(第\s*)?\d{1,4}\s*(/\s*\d{1,4})?\s*页?\s*(共\s*\d{1,4}\s*页)?\s*$"),
    # Page X / Page X of Y / p. X / pp. X-Y
    re.compile(r"^\s*Page\s*\d{1,4}(\s*of\s*\d{1,4})?\s*$", re.IGNORECASE),
    re.compile(r"^\s*p\.?\s*\d{1,4}\s*$", re.IGNORECASE),
    re.compile(r"^\s*pp\.?\s*\d{1,4}\s*[-\u2013\u2014]\s*\d{1,4}\s*$", re.IGNORECASE),
    # - 12 - / — 12 — / · 12 ·
    re.compile(r"^\s*[-\u2013\u2014\u00b7\u00b7]\s*\d{1,4}\s*[-\u2013\u2014\u00b7\u00b7]\s*$"),
)


def is_page_number_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s.startswith("#"):  # 永远不当成页码
        return False
    return any(p.match(s) for p in _PAGE_NUMBER_PATS)


def remove_page_numbers(text: str) -> tuple[str, int]:
    """删除所有页码行；返回 ``(cleaned_text, 删除行数)``。"""
    if not text:
        return text, 0
    n = 0
    out: list[str] = []
    for ln in text.split("\n"):
        if is_page_number_line(ln):
            n += 1
            continue
        out.append(ln)
    return "\n".join(out), n


__all__ = ["is_page_number_line", "remove_page_numbers"]
