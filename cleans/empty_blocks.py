"""空标题 / 空段落 / 空 bullet 的最终整理。

覆盖的场景
----------
- 空标题：``#``、``##  ``、``###`` —— 仅有 hash + 空白；
- 空 bullet：``- ``、``*  ``、``+ ``、``- -``、``*  *`` —— 仅有 bullet 字符；
- 空带数字的有序列表项：``1.``、``2)``、``3、`` —— 仅有编号；
- 多个连续空 bullet：归并为 0 行（不保留任何无信息空项）；
- 连续 ≥ 3 个 ``\\n`` → 折叠为 2 个（与 ``finalize_for_kb`` 一致，再兜底一次）。
"""

from __future__ import annotations

import re

_EMPTY_HEADING = re.compile(r"^\s*#{1,6}\s*$")
_EMPTY_BULLET = re.compile(r"^\s*[-*+]\s*$")
_EMPTY_BULLET_DUP = re.compile(r"^\s*[-*+](\s*[-*+])+\s*$")
_EMPTY_ORDERED = re.compile(r"^\s*\d+\s*[\.\)、]\s*$")


def _is_empty_block_line(line: str) -> bool:
    if _EMPTY_HEADING.match(line):
        return True
    if _EMPTY_BULLET.match(line):
        return True
    if _EMPTY_BULLET_DUP.match(line):
        return True
    if _EMPTY_ORDERED.match(line):
        return True
    return False


def remove_empty_blocks(text: str) -> tuple[str, int]:
    """删除空标题 / 空 bullet / 空编号项；再折叠多余空行。

    Returns:
        ``(cleaned_text, 被删除的行数)``。注意"被删行数"不包括连续空行折叠出来的差值，
        只计真正命中空块模式的行。
    """
    if not text:
        return text, 0

    n = 0
    out: list[str] = []
    for ln in text.split("\n"):
        if _is_empty_block_line(ln):
            n += 1
            continue
        out.append(ln)

    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, n


__all__ = ["remove_empty_blocks"]
