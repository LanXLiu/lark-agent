"""跨页重复短行（页眉 / 页脚）检测与剔除。

算法
----
1. 把 Markdown 按页标记切分为「页」：

   - ``<!-- page: N -->``   — PPT 视觉版（``pptx_visual_to_markdown``）输出；
   - ``## Page N``           — PDF 扫描分页 OCR（``convert_scanned_pdf_pages_to_markdown``）输出。

   两种都识别；不足 3 页则**不做任何处理**（样本太少无法判定重复）。

2. 对每页收集「短文本行」候选（``len ≤ short_line_max``，默认 30 字），
   并在 **页内做一次去重**——同页内出现 N 次的同一行只计 1 次。

3. 在所有页里统计每个候选短行出现的「页数」。

4. 出现在 ``ratio ≥ threshold`` 个页的候选 → 判定为页眉 / 页脚 → **整行删除**
   （所有出现位置一并删，不只是首尾）。

候选行的排除规则（避免误删正文）
-----------------------------
- 空行 / 长行（> ``short_line_max``）；
- 页标记本身（``<!-- page: N -->`` / ``## Page N``）；
- Markdown 标题行（``#``/``##``/``###`` ...）—— 防止 ``## 标题`` 因 VLM
  偶尔给出相同短句被误删；
- 装饰行（``---`` / ``═══`` 等）—— 这些有专门的清洗步骤处理。

返回
----
``(cleaned_text, repeated_lines)``，``repeated_lines`` 是被判定为页眉 / 页脚
并已从文本中剔除的字符串列表（去重后），可写入 ``metadata`` 供审计。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

# 兼容两种页标记
_HTML_PAGE_MARK = re.compile(r"^\s*<!--\s*page\s*:\s*(\d+)\s*-->\s*$", re.IGNORECASE)
_HASH_PAGE_MARK = re.compile(r"^\s*##\s+Page\s+(\d+)\s*$", re.IGNORECASE)

# 标题行（# / ## / ### ...）——不参与短行候选
_HEADING_LINE = re.compile(r"^\s*#{1,6}\s+\S")

# 装饰行（保守版；与 decoration.py 同步）——不参与短行候选
_DECORATION_LINE = re.compile(
    r"^\s*(?:"
    r"[-*_=]{3,}"
    r"|[\u2500-\u259f]{2,}"
    r"|[═━─—…·]{3,}"
    r")\s*$"
)


def _is_page_mark(line: str) -> bool:
    return bool(_HTML_PAGE_MARK.match(line) or _HASH_PAGE_MARK.match(line))


def _norm(line: str) -> str:
    """页眉页脚匹配前的归一化：NFC + 去首尾空白。"""
    return unicodedata.normalize("NFC", line.strip())


def _split_pages(text: str) -> list[list[str]] | None:
    """按页标记切分为 list[list[str]]；不足 3 页返回 None。

    切分策略：把 ``page mark`` 行作为「下一页起点」。任何 mark 之前的内容
    （通常是 ``# 文档标题`` / 第一页 ``## 标题``）会归入第 1 页的桶。
    这种轻微的"错位"不影响跨页重复行的统计——因为标题行和页标记都已经
    在候选阶段被排除。
    """
    lines = text.split("\n")
    indices = [i for i, ln in enumerate(lines) if _is_page_mark(ln)]
    if len(indices) < 3:
        return None

    pages: list[list[str]] = []
    # 第一段：从文档开头到第 1 个 mark 之前（含前置 # 标题 / 段落）
    pages.append(lines[: indices[0]])
    # 中间段：每个 mark 到下一个 mark 之前
    for k, start in enumerate(indices):
        end = indices[k + 1] if k + 1 < len(indices) else len(lines)
        pages.append(lines[start:end])
    return pages


def _collect_short_lines(page: list[str], *, short_line_max: int) -> set[str]:
    """提取一页内可参与跨页统计的"短行候选"（页内去重）。"""
    cands: set[str] = set()
    for ln in page:
        if _is_page_mark(ln):
            continue
        if _HEADING_LINE.match(ln):
            continue
        if _DECORATION_LINE.match(ln):
            continue
        s = _norm(ln)
        if not s:
            continue
        if len(s) > short_line_max:
            continue
        cands.add(s)
    return cands


def remove_repeated_headers_footers(
    text: str,
    *,
    threshold: float = 0.5,
    short_line_max: int = 30,
    min_pages: int = 3,
) -> tuple[str, list[str]]:
    """删除跨页重复的"短行"。

    Args:
        text: 完整 Markdown 文本。
        threshold: 命中阈值，0.5 表示「至少在 50% 的页里出现过」就算页眉 / 页脚。
        short_line_max: 候选行的最大长度（字符数，含空格）。
        min_pages: 不足这么多页时直接返回原文（默认 3，2 页文档不可靠）。

    Returns:
        ``(cleaned_text, repeated_lines)``。``repeated_lines`` 已按归一化后字符串
        去重，可直接写入 metadata。
    """
    if not text or not text.strip():
        return text, []

    pages = _split_pages(text)
    if pages is None or len(pages) < min_pages:
        return text, []

    n_pages = len(pages)
    counter: Counter[str] = Counter()
    for page in pages:
        for s in _collect_short_lines(page, short_line_max=short_line_max):
            counter[s] += 1

    # 至少出现 ceil(threshold * n_pages) 次，并至少 ≥ 2 次（再低无意义）
    cutoff = max(2, int(round(threshold * n_pages)))
    repeated = sorted({s for s, n in counter.items() if n >= cutoff})
    if not repeated:
        return text, []

    repeated_set = set(repeated)
    out: list[str] = []
    for ln in text.split("\n"):
        if _is_page_mark(ln):
            out.append(ln)
            continue
        if _norm(ln) in repeated_set:
            continue
        out.append(ln)
    return "\n".join(out), repeated


__all__ = ["remove_repeated_headers_footers"]
