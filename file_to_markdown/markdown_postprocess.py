"""知识库导向的 Markdown 归一化与清洗（统一出口）。

供 ``unified_entry``、``pipeline.steps.cleaner`` 与各转换器复用，
避免各处重复实现空白折叠、零宽字符剥离等逻辑。
"""

from __future__ import annotations

import re
import unicodedata

# 与历史 TextCleanerStep 对齐的噪声模式
_PIPELINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[ \t]+"), " "),
    (re.compile(r"\n{4,}"), "\n\n\n"),
    (re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]"), ""),
    (re.compile(r"[^\S\n]{2,}"), " "),
]

_ORPHAN_LIST = re.compile(r"(?:^\s*[-*]\s*$)+", re.MULTILINE)

_ZW_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")

_HTML_TAG = re.compile(r"</?[a-zA-Z][\w:-]*(?:\s[^>]*)?>")

# pipe 表识别：以 `|` 起步、含至少两个 `|`；分隔行只含 `-`/`:`/`空格`/`|`。
_PIPE_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_PIPE_TABLE_SEP_CELL = re.compile(r"^\s*:?-+:?\s*$")


def _is_pipe_separator_row(line: str) -> bool:
    """识别 `| --- | --- |` 这种 markdown 表对齐分隔行。"""
    if not _PIPE_TABLE_ROW.match(line):
        return False
    cells = [c for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(_PIPE_TABLE_SEP_CELL.match(c) for c in cells)


def _convert_residual_pipe_tables(t: str) -> str:
    """
    把残留的 ``| ... |`` markdown 表格转成「字段名：内容 字段名：内容」纯文本。

    主要给 PDF / 图片 OCR / VLM 输出等**非控制源**做兜底——Excel / Word / PPT 已经
    在源头直接产出 field:value 文本，不会进入这条路径。识别规则：

    - 连续至少 2 行以 ``|`` 起步且含 >=2 个 ``|``；
    - 至少有一行是「分隔行」（``| --- | --- |``）；
    - 取第一行为表头；其余非分隔行为数据；
    - 任一条件不满足则原样保留。
    """
    if "|" not in t:
        return t

    from .table_renderer import table_to_field_value_text

    lines = t.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _PIPE_TABLE_ROW.match(line):
            j = i
            block: list[str] = []
            while j < n and _PIPE_TABLE_ROW.match(lines[j]):
                block.append(lines[j])
                j += 1
            has_sep = any(_is_pipe_separator_row(b) for b in block)
            if len(block) >= 2 and has_sep:
                rows = [
                    [c.strip() for c in b.strip().strip("|").split("|")]
                    for b in block
                    if not _is_pipe_separator_row(b)
                ]
                if len(rows) >= 2:
                    headers, data_rows = rows[0], rows[1:]
                    fv = table_to_field_value_text(headers, data_rows)
                    if fv:
                        out.append(fv)
                        i = j
                        continue
                elif len(rows) == 1:
                    # 只有表头没数据，丢弃整段（不留无信息的孤行）
                    i = j
                    continue
            # 不是合法 pipe 表，原样输出本行
            out.append(line)
            i += 1
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


def finalize_for_kb(text: str, *, html_fallback: bool = True) -> str:
    """统一收尾：换行、零宽字符、尾部空白；可选将残留 HTML 转为 Markdown。

    并对任何残留 ``| ... |`` markdown 表格做兜底转换，统一为
    「字段名：内容 字段名：内容」纯文本格式（与 Excel / Word / PPT 等源头一致）。
    """
    if not text or not text.strip():
        return ""

    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = _ZW_RE.sub("", t)

    lines_out: list[str] = []
    for line in t.split("\n"):
        line = unicodedata.normalize("NFC", line.rstrip())
        lines_out.append(line)
    t = "\n".join(lines_out)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = t.strip()

    if html_fallback and _HTML_TAG.search(t):
        from .html_to_markdown import HtmlToMarkdownConverter

        try:
            converted = HtmlToMarkdownConverter().convert(t)
            if len(converted.strip()) >= max(20, int(len(t.strip()) * 0.25)):
                t = converted.strip()
        except Exception:
            pass

    # pipe 表 → field:value 文本（兜底；源头已改造的路径不会触发）
    t = _convert_residual_pipe_tables(t)
    # 兜底转换后可能产生多余空行，统一收一次
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    return t


def clean_for_pipeline(text: str) -> str:
    """管线专用：先应用与 TextCleanerStep 相同的规则，再 ``finalize_for_kb``。"""
    if not text:
        return ""

    t = text
    for pattern, repl in _PIPELINE_PATTERNS:
        t = pattern.sub(repl, t)

    lines = t.split("\n")
    cleaned = [ln for ln in lines if not _ORPHAN_LIST.match(ln)]
    t = "\n".join(cleaned).strip()

    return finalize_for_kb(t, html_fallback=False)
