"""KB-oriented Markdown 清洗模块。

把"对 RAG / 向量化无价值"的噪声集中处理：

★★★ 高优先

- :func:`remove_repeated_headers_footers` —— 跨页重复短行（页眉 / 页脚）；
- :func:`remove_page_numbers`              —— 单独成行的页码（中英多种格式）；
- :func:`remove_toc_blocks`                —— 目录 (TOC) 段（点状对齐 + 标题+列表 两种模式）。

★★ 中优先

- :func:`remove_closing_thanks`            —— 结束 / 致谢 / Q&A 收尾行（THANK YOU / 谢谢 / 完 等）；
- :func:`remove_decorative_lines`          —— 装饰横线 / 全角分隔（``---/═══/——/===`` 等）；
- :func:`remove_empty_blocks`              —— 空标题 / 空 bullet / 空编号项；
- :func:`remove_duplicate_paragraphs`      —— 整段精确去重（仅保留首次出现）；
- :func:`remove_legal_boilerplate`         —— 文档尾部的版权 / 免责声明 / 保密模板段。

设计原则
--------
1. **每条规则单独成文件**，可独立测试、独立启用；
2. **保留页标记**（``<!-- page: N -->`` / ``## Page N``）作为溯源锚点，
   清洗本身不破坏它们；
3. 统一返回 :class:`CleanResult`（``text + metadata``），元数据可写回入库
   管线供审计；
4. 调用入口在 :func:`file_to_markdown.unified_entry.convert_bytes` 的
   ``finalize_for_kb`` **之后**执行，所有格式（PDF / DOCX / PPT / XLSX / 图片 / JSON）
   都会经过这条清洗链。

典型用法::

    from knowledge.ingestion.cleans import clean_markdown

    result = clean_markdown(markdown_text)
    print(result.text)       # 清洗后的 Markdown
    print(result.metadata)   # 命中类型与数量，e.g. {"removed_page_numbers": 4, ...}

自定义启用项 / 阈值::

    from knowledge.ingestion.cleans import MarkdownCleaner

    cleaner = MarkdownCleaner(
        remove_boilerplate=False,        # 不删尾段模板
        header_footer_threshold=0.6,     # 至少 60% 的页都出现才算页眉/页脚
    )
    result = cleaner.clean(markdown_text)

也可以单独调用某一步（适合在 notebook 里精确做 A/B）::

    from knowledge.ingestion.cleans import remove_toc_blocks

    cleaned, toc_lines = remove_toc_blocks(md, min_consecutive=4)
"""

from __future__ import annotations

from typing import Any

from .base import CleanResult
from .boilerplate import remove_legal_boilerplate
from .closing import is_closing_line, remove_closing_thanks
from .decoration import is_decoration_line, remove_decorative_lines
from .dedup import remove_duplicate_paragraphs
from .empty_blocks import remove_empty_blocks
from .header_footer import remove_repeated_headers_footers
from .page_number import is_page_number_line, remove_page_numbers
from .pipeline import MarkdownCleaner
from .short_noise import remove_short_noise_lines
from .toc import is_toc_line, remove_toc_blocks


def clean_markdown(text: str, **kwargs: Any) -> CleanResult:
    """便捷入口：等价于 ``MarkdownCleaner(**kwargs).clean(text)``。

    ``**kwargs`` 直接转发给 :class:`MarkdownCleaner`，支持开关各类清洗
    或调阈值。
    """
    return MarkdownCleaner(**kwargs).clean(text)


__all__ = [
    "CleanResult",
    "MarkdownCleaner",
    "clean_markdown",
    "is_closing_line",
    "is_decoration_line",
    "is_page_number_line",
    "is_toc_line",
    "remove_closing_thanks",
    "remove_decorative_lines",
    "remove_duplicate_paragraphs",
    "remove_empty_blocks",
    "remove_legal_boilerplate",
    "remove_page_numbers",
    "remove_repeated_headers_footers",
    "remove_short_noise_lines",
    "remove_toc_blocks",
]
