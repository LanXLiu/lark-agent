"""目录（TOC）段识别与剔除。

两种识别模式
------------

**模式 A：点状对齐目录**（书籍 / 长文档常见）::

    第一章 概述 ............... 1
    1.1 简介 ········ 5
    Chapter One ........... 1

正则（任一命中）：

- ``^.+?[\\.·…\\s]{0,4}[\\.·…]{3,}[\\.·…\\s]{0,4}\\d{1,4}\\s*$``
  —— 「文本 + 至少 3 个点状字符 + 数字」结尾；
- 还兼容用 ``─`` ``━`` ``－`` 等线条字符串联的奇葩排版。

**模式 B：列表式目录**（PPT 议程页 / 大纲页常见）::

    ## 目录
    <!-- page: 12 -->

    - 1 公司介绍
    - 2 需求理解
    - 3 WMS核心功能
    ...

识别规则：

- ``#`` ~ ``######`` 的标题文本命中以下关键词之一即触发：
  ``目录`` / ``目次`` / ``大纲`` / ``提纲`` / ``议程`` /
  ``Contents`` / ``Table of Contents`` / ``Outline`` / ``Agenda`` / ``Index``
- 标题之后允许夹**空行 / 页标记**，再紧跟着 **连续 ≥ ``min_consecutive``** 个 ``- ``
  / ``* `` / ``1.`` / ``1)`` 列表项 → 判定整块为目录，删除「标题 + 所有列表项」。
- 块内的 ``<!-- page: N -->`` 页标记**保留**（便于跨页溯源 / 后续 header/footer 检测）。

整段判定（共用）
----------------
**仅当连续 ≥ ``min_consecutive`` 行**都匹配 TOC 模式时，才认为是真正的目录段，
整段一并删除并收集到 ``metadata.toc``。这样可以避免误删正文里偶然出现的
``See Note 1`` 这类"看起来像但只有 1 行"的情况。
"""

from __future__ import annotations

import re

# ----- 模式 A：点状对齐目录 -----
_TOC_LINE_RE = re.compile(
    r"^.{1,120}?"
    r"[\.·…\u2014\u2013\u2500\u2501\u2015\s]{0,4}"
    r"[\.·…\u2014\u2013\u2500\u2501\u2015]{3,}"
    r"[\.·…\u2014\u2013\u2500\u2501\u2015\s]{0,4}"
    r"\d{1,4}\s*$"
)

# ----- 模式 B：列表式目录 -----
_TOC_HEADING_RE = re.compile(
    r"^\s*#{1,6}\s+"
    r"(?:"
    r"目\s*录|目\s*次|大\s*纲|提\s*纲|议\s*程|"
    r"Table\s+of\s+Contents?|Contents?|Outline|Agenda|Index"
    r")\s*$",
    re.IGNORECASE,
)

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\s*[\.\)、])\s+\S")
_PAGE_MARK_RE = re.compile(
    r"^\s*(?:<!--\s*page\s*:\s*\d+\s*-->|##\s+Page\s+\d+)\s*$",
    re.IGNORECASE,
)


def is_toc_line(line: str) -> bool:
    """是否为「模式 A：点状对齐」的单行 TOC。"""
    s = line.strip()
    if not s:
        return False
    if s.startswith("#") or s.startswith("|"):
        return False
    if len(s) > 200:
        return False
    return bool(_TOC_LINE_RE.match(s))


def _remove_list_style_toc(
    text: str,
    *,
    min_consecutive: int = 3,
) -> tuple[str, list[str]]:
    """删除「模式 B：标题 + 列表项」的目录块；返回 ``(cleaned, removed_lines)``。"""
    lines = text.split("\n")
    n = len(lines)
    out: list[str] = []
    collected: list[str] = []
    i = 0

    while i < n:
        if not _TOC_HEADING_RE.match(lines[i]):
            out.append(lines[i])
            i += 1
            continue

        # 试探：从 heading 之后跳过空行 / 页标记，收集连续 list 项
        j = i + 1
        list_indices: list[int] = []
        page_mark_indices: list[int] = []
        while j < n:
            ln = lines[j]
            if not ln.strip():
                # 允许空行夹在中间
                j += 1
                continue
            if _PAGE_MARK_RE.match(ln):
                page_mark_indices.append(j)
                j += 1
                continue
            if _LIST_ITEM_RE.match(ln):
                list_indices.append(j)
                j += 1
                continue
            break  # 命中非空 / 非 list 行 → 块结束

        if len(list_indices) >= min_consecutive:
            # 整块删除：heading + 所有 list 项；空行 / 页标记**保留**以维护溯源
            collected.append(lines[i])  # heading
            collected.extend(lines[k] for k in list_indices)
            removed = set(list_indices) | {i}
            # 回填空行 + 页标记之间的内容（在 i+1 ~ j-1 之间但不在 removed 集合）
            for k in range(i + 1, j):
                if k in removed:
                    continue
                # 在 list block 范围内的空行也吃掉，避免留一大堆空白
                if not lines[k].strip():
                    continue
                out.append(lines[k])
            i = j
            continue

        out.append(lines[i])
        i += 1

    return "\n".join(out), collected


def _remove_dot_leader_toc(
    text: str,
    *,
    min_consecutive: int = 3,
) -> tuple[str, list[str]]:
    """删除「模式 A：点状对齐」目录段；返回 ``(cleaned, removed_lines)``。"""
    lines = text.split("\n")
    out: list[str] = []
    collected: list[str] = []
    i, n = 0, len(lines)

    while i < n:
        if is_toc_line(lines[i]):
            j = i
            # 把"夹在 TOC 行之间的空行"也吸进同一个 block，避免段内空行打断识别
            while j < n:
                if is_toc_line(lines[j]):
                    j += 1
                    continue
                if not lines[j].strip() and j + 1 < n and is_toc_line(lines[j + 1]):
                    j += 1
                    continue
                break

            block = lines[i:j]
            toc_only = [b for b in block if is_toc_line(b)]
            if len(toc_only) >= min_consecutive:
                collected.extend(toc_only)
                i = j
                continue
        out.append(lines[i])
        i += 1

    return "\n".join(out), collected


def remove_toc_blocks(
    text: str,
    *,
    min_consecutive: int = 3,
) -> tuple[str, list[str]]:
    """识别并删除目录段（**两种模式同时启用**）。

    Args:
        text: 完整 Markdown 文本。
        min_consecutive: 模式 A 的连续匹配阈值、模式 B 的最少列表项数（默认 3）。

    Returns:
        ``(cleaned_text, toc_lines)``。``toc_lines`` 是被识别为目录的原始行
        （**未做归一化**，保留原始字符以便复盘），可塞进 ``metadata.toc``。
    """
    if not text:
        return text, []

    text, list_toc = _remove_list_style_toc(text, min_consecutive=min_consecutive)
    text, dot_toc = _remove_dot_leader_toc(text, min_consecutive=min_consecutive)
    return text, list_toc + dot_toc


__all__ = ["is_toc_line", "remove_toc_blocks"]
