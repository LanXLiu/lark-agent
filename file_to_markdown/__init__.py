"""
文档转 Markdown 工具包。

提供 HTML/Word/PDF/图片/JSON 等转换与 ``unified_entry`` 统一入口；
图像 PP-Structure 依赖可选安装 ``paddlepaddle`` + ``paddleocr``。
管线级文本清洗见 ``markdown_postprocess``。
"""

from .html_to_markdown import HtmlToMarkdownConverter
from .image_to_markdown import ImageToMarkdownConverter, get_image_to_markdown_converter
from .json_to_markdown import JsonToMarkdownConverter
from .markdown_postprocess import clean_for_pipeline, finalize_for_kb
from .pdf_to_markdown import (
    PdfToMarkdownConverter,
    convert_other_to_markdown,
    convert_pdf_bytes_unified,
    convert_scanned_pdf_pages_to_markdown,
    is_pdf_scanned,
    is_text_content_insufficient,
)
from .structured_exporters import excel_bytes_to_markdown, pptx_bytes_to_markdown
from .unified_entry import DocumentConversionResult, convert_bytes, convert_file_to_markdown
from .word_to_markdown import WordToMarkdownConverter

__all__ = [
    "HtmlToMarkdownConverter",
    "ImageToMarkdownConverter",
    "JsonToMarkdownConverter",
    "PdfToMarkdownConverter",
    "WordToMarkdownConverter",
    "DocumentConversionResult",
    "clean_for_pipeline",
    "convert_bytes",
    "convert_file_to_markdown",
    "convert_other_to_markdown",
    "convert_pdf_bytes_unified",
    "convert_scanned_pdf_pages_to_markdown",
    "excel_bytes_to_markdown",
    "finalize_for_kb",
    "get_image_to_markdown_converter",
    "is_pdf_scanned",
    "is_text_content_insufficient",
    "pptx_bytes_to_markdown",
]
