"""跨段精确去重。

适用场景
--------
某些 PPT / Word 文档里会"整段"重复出现：

- 每页底部都贴着"公司机密 + 请勿外传 + 版权所有"这样的 **多行**模板
  （``header_footer`` 只删短行，对**多行段落**无能为力）；
- 模板水印性的段落："本资料仅供项目内部讨论使用"；
- 视觉版 PPT 抄录时偶发的 "本页讲述..."、"图中展示..." 等导语段重复 4-5 次；
- 介绍页 / 议程页被复制粘贴到末页。

实现思路
--------
1. 按 ``\\n\\n`` 切段，对每段做 NFC + 折叠空白后取归一化形式作为 key；
2. **标题段、纯页标记段、长度过短的段**不参与去重，避免删掉合法的 ``## Slide N`` /
   ``<!-- page: N -->`` / 简短人名等；
3. 出现次数 ≥ ``min_occurrences`` 的归一化段，**仅保留第一次出现**，其余删除；
4. 返回 ``(cleaned_text, 被删除的段落数)``。
"""

from __future__ import annotations

import re
import unicodedata

_PAGE_MARK_RE = re.compile(
    r"^\s*(?:<!--\s*page\s*:\s*\d+\s*-->|##\s+Page\s+\d+)\s*$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")
_WS_RE = re.compile(r"\s+")


def _norm_paragraph(p: str) -> str:
    """段落归一化用于比较：行级 NFC + 去首尾空白 + 折叠内部空白 + 空行剔除。"""
    if not p:
        return ""
    rows: list[str] = []
    for ln in p.split("\n"):
        ln = unicodedata.normalize("NFC", ln).strip()
        if not ln:
            continue
        rows.append(_WS_RE.sub(" ", ln))
    return "\n".join(rows)


def _is_protected_paragraph(p: str) -> bool:
    """段落是否豁免去重：空段 / 全是页标记 / 全是标题行。"""
    stripped = p.strip()
    if not stripped:
        return True
    lines = [ln for ln in stripped.split("\n") if ln.strip()]
    if not lines:
        return True
    if all(_PAGE_MARK_RE.match(ln) for ln in lines):
        return True
    if all(_HEADING_RE.match(ln) for ln in lines):
        return True
    return False


def remove_duplicate_paragraphs(
    text: str,
    *,
    min_chars: int = 20,
    min_occurrences: int = 2,
) -> tuple[str, int]:
    """
    删除整段精确重复，**只保留首次出现**。

    Args:
        text: 完整 Markdown 文本。
        min_chars: 段落归一化后字符数 < 此值不参与去重（避免误删短句 / 短名）。
        min_occurrences: 出现次数达到此值即视为重复段（默认 2 = 重复 2 次起删除多余的）。

    Returns:
        ``(cleaned_text, 被删除的段落数)``。**未做归一化的原文段落**保留在结果中。
    """
    if not text or not text.strip():
        return text, 0

    paragraphs = text.split("\n\n")
    if len(paragraphs) <= 1:
        return text, 0

    norm_list: list[str] = [_norm_paragraph(p) for p in paragraphs]

    counts: dict[str, int] = {}
    for n in norm_list:
        if len(n) < min_chars:
            continue
        counts[n] = counts.get(n, 0) + 1

    repeats = {k for k, v in counts.items() if v >= min_occurrences}
    if not repeats:
        return text, 0

    kept_first: set[str] = set()
    removed = 0
    out: list[str] = []
    for orig, norm in zip(paragraphs, norm_list):
        if _is_protected_paragraph(orig):
            out.append(orig)
            continue
        if norm in repeats:
            if norm in kept_first:
                removed += 1
                continue
            kept_first.add(norm)
        out.append(orig)

    if removed == 0:
        return text, 0
    cleaned = "\n\n".join(out)
    # 段间多余空行（被删段两侧的 \n\n 叠加）兜底压一次
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, removed


__all__ = ["remove_duplicate_paragraphs"]
