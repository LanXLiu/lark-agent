"""把所有清洗步骤串成一个可配置编排器。

执行顺序（**有意为之，不要随意调整**）::

    1) header / footer 跨页重复短行     —— 需要原始页标记，必须在前
    2) 页码行                           —— 删行不破坏结构
    3) TOC 目录段                       —— 段落级（含「点状对齐」与「标题+列表」两种），
                                          先于装饰线，方便 TOC 段尾的横线一并删
    4) 结束 / 致谢 / Q&A 收尾行          —— 行级；先于装饰线 + 空块，吃掉「## 谢谢」此类
    5) 极短中文噪声行                    —— 如 ``（上）``，保留标题 / 列表 / 表格
    6) 装饰横线 / 全角分隔
    7) 空标题 / 空 bullet               —— 在以上删行之后执行，吃掉留下的"空坑"
    8) 整段精确去重                      —— 此时噪声最少，命中率最高；可设最小长度阈值
    9) 法律免责声明 / 模板尾段           —— 仅扫描尾部，最后做

每一步都把 ``(text, count_or_list)`` 写回 ``metadata``，命中才出现字段；没命中
就不污染元数据。最后做一次 ``\\n{3,} → \\n\\n`` 兜底压缩。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .base import CleanResult
from .boilerplate import remove_legal_boilerplate
from .closing import remove_closing_thanks
from .decoration import remove_decorative_lines
from .dedup import remove_duplicate_paragraphs
from .empty_blocks import remove_empty_blocks
from .header_footer import remove_repeated_headers_footers
from .page_number import remove_page_numbers
from .short_noise import remove_short_noise_lines
from .toc import remove_toc_blocks


@dataclass
class MarkdownCleaner:
    """配置化的 Markdown 清洗器。

    所有开关默认 ``True``，每一步都可以单独关掉做 A/B；阈值也可调。

    Args:
        remove_headers_footers:        是否检测跨页重复短行（页眉 / 页脚）。
        remove_page_numbers:           是否删除整行就是页码的行。
        remove_toc:                    是否识别并删除目录段（点状对齐 + 标题+列表 两种模式）。
        remove_closing:                是否删除「THANK YOU / 感谢您的聆听 / Q&A / 完」等结束行。
        remove_short_noise:            是否删除 ``（上）`` 这类极短中文噪声行。
        remove_decoration:             是否删除装饰横线 / 全角分隔行。
        remove_empty_blocks:           是否删除空标题 / 空 bullet / 空编号项。
        remove_duplicates:             是否做"跨段精确去重"（按整段归一化匹配）。
        remove_boilerplate:            是否扫描尾部 N 段删除版权 / 免责声明等模板段。
        header_footer_threshold:       跨页重复阈值（默认 0.5 = 一半的页里都出现就删）。
        header_footer_short_line_max:  候选短行最大字符数（默认 30）。
        toc_min_consecutive:           连续多少行匹配 TOC 模式才视作目录段（默认 3）。
        keep_toc_in_metadata:          删 TOC 时，是否把原始行写入 ``metadata.toc``。
        boilerplate_tail_paragraphs:   仅扫描文末多少段查找模板（默认 5）。
        duplicate_min_chars:           整段去重时段落归一化后最少字符数（默认 20）。
        duplicate_min_occurrences:     ≥ 此次数才视为"重复段"（默认 2 = 出现 2 次起就只留 1 个）。
        short_noise_min_cjk_chars:     短噪声行最少中文字数，少于该值则删除（默认 8）。
    """

    remove_headers_footers: bool = True
    remove_page_numbers: bool = True
    remove_toc: bool = True
    remove_closing: bool = True
    remove_short_noise: bool = True
    remove_decoration: bool = True
    remove_empty_blocks: bool = True
    remove_duplicates: bool = True
    remove_boilerplate: bool = True

    header_footer_threshold: float = 0.5
    header_footer_short_line_max: int = 30
    toc_min_consecutive: int = 3
    keep_toc_in_metadata: bool = True
    boilerplate_tail_paragraphs: int = 5
    duplicate_min_chars: int = 20
    duplicate_min_occurrences: int = 2
    short_noise_min_cjk_chars: int = 8

    def clean(self, text: str) -> CleanResult:
        if not text or not text.strip():
            return CleanResult(text=text, metadata={})

        meta: dict[str, Any] = {}
        t = text

        if self.remove_headers_footers:
            t, repeated = remove_repeated_headers_footers(
                t,
                threshold=self.header_footer_threshold,
                short_line_max=self.header_footer_short_line_max,
            )
            if repeated:
                meta["removed_headers_footers"] = repeated
                meta["removed_headers_footers_count"] = len(repeated)

        if self.remove_page_numbers:
            t, n_pn = remove_page_numbers(t)
            if n_pn:
                meta["removed_page_numbers"] = n_pn

        if self.remove_toc:
            t, toc_lines = remove_toc_blocks(
                t, min_consecutive=self.toc_min_consecutive
            )
            if toc_lines:
                meta["removed_toc_lines"] = len(toc_lines)
                if self.keep_toc_in_metadata:
                    meta["toc"] = toc_lines

        if self.remove_closing:
            t, n_cl = remove_closing_thanks(t)
            if n_cl:
                meta["removed_closing_lines"] = n_cl

        if self.remove_short_noise:
            t, n_short = remove_short_noise_lines(
                t,
                min_cjk_chars=self.short_noise_min_cjk_chars,
            )
            if n_short:
                meta["removed_short_noise_lines"] = n_short

        if self.remove_decoration:
            t, n_dec = remove_decorative_lines(t)
            if n_dec:
                meta["removed_decoration_lines"] = n_dec

        if self.remove_empty_blocks:
            t, n_eb = remove_empty_blocks(t)
            if n_eb:
                meta["removed_empty_blocks"] = n_eb

        if self.remove_duplicates:
            t, n_dup = remove_duplicate_paragraphs(
                t,
                min_chars=self.duplicate_min_chars,
                min_occurrences=self.duplicate_min_occurrences,
            )
            if n_dup:
                meta["removed_duplicate_paragraphs"] = n_dup

        if self.remove_boilerplate:
            t, n_bp = remove_legal_boilerplate(
                t, tail_paragraphs=self.boilerplate_tail_paragraphs
            )
            if n_bp:
                meta["removed_boilerplate_paragraphs"] = n_bp

        # 兜底：连续 ≥3 空行折叠 + 修首尾
        t = re.sub(r"\n{3,}", "\n\n", t).strip()

        return CleanResult(text=t, metadata=meta)


__all__ = ["MarkdownCleaner"]
