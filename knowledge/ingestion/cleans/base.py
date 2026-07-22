"""清洗模块的轻量数据结构。

只放与"输出"相关的 dataclass，避免循环依赖。具体清洗函数实现在同级
``header_footer`` / ``page_number`` / ``toc`` / ``decoration`` / ``empty_blocks``
/ ``boilerplate`` 模块里，由 :class:`pipeline.MarkdownCleaner` 串起来。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CleanResult:
    """一次 Markdown 清洗的结构化结果。

    ``metadata`` 里**只放真正命中的清洗类型**（如 ``removed_page_numbers=4``），
    没命中的字段不出现，便于上层落库时直接 ``json.dumps`` 不会塞一堆 0/[] 噪声。
    """

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = ["CleanResult"]
