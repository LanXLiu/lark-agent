"""删除极短中文噪声行。

典型场景是 OCR / 版式转换残留的 ``（上）``、``上``、``附`` 这类单独一行。
为了避免误删结构信息，本步骤不会删除 Markdown 标题、列表、表格、页标记、
字段标签行（含 ``:`` / ``：``）或包含英文/数字的行。
"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_HAS_LATIN_OR_DIGIT = re.compile(r"[A-Za-z0-9]")
_MARKDOWN_STRUCTURAL = re.compile(
    r"^\s*(#{1,6}\s+|[-*+]\s+|\d+\s*[\.\)、]\s+|>\s*|\|)"
)
_PAGE_COMMENT = re.compile(r"^\s*<!--\s*page:\s*\d+\s*-->\s*$", re.IGNORECASE)


def remove_short_noise_lines(text: str, *, min_cjk_chars: int = 8) -> tuple[str, int]:
    """删除有效中文字数少于 ``min_cjk_chars`` 的孤立噪声行。

    Returns:
        ``(cleaned_text, removed_count)``。
    """
    if not text:
        return text, 0

    removed = 0
    out: list[str] = []

    for line in text.split("\n"):
        if _is_short_noise_line(line, min_cjk_chars=min_cjk_chars):
            removed += 1
            continue
        out.append(line)

    return "\n".join(out), removed


def _is_short_noise_line(line: str, *, min_cjk_chars: int) -> bool:
    stripped = line.strip()
    if not stripped:
        return False

    if _PAGE_COMMENT.match(stripped):
        return False
    if _MARKDOWN_STRUCTURAL.match(stripped):
        return False
    if ":" in stripped or "：" in stripped:
        return False
    if _HAS_LATIN_OR_DIGIT.search(stripped):
        return False

    cjk_chars = _CJK_RE.findall(stripped)
    if not cjk_chars:
        return False
    return len(cjk_chars) < min_cjk_chars


__all__ = ["remove_short_noise_lines"]
