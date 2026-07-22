"""
PDF 文档转换器（薄封装）。

实际转换逻辑由 ``file_to_markdown.unified_entry`` 统一完成（含扫描件分页 OCR 等）。
"""

from pathlib import Path

from knowledge.ingestion.converter.base import BaseConverter, ConversionResult, convert_via_file_to_markdown


class PdfConverter(BaseConverter):
    """
    PDF → Markdown 转换器。

    仅声明支持 ``.pdf``，具体策略由统一入口根据内容选择文本或 OCR 路径。
    """

    supported_extensions = (".pdf",)

    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        异步调用统一转换入口。

        Args:
            file_path: PDF 文件路径。
            **kwargs: 如 ``max_scanned_pages`` 等，透传至 ``convert_file_to_markdown``。

        Returns:
            ``ConversionResult``。
        """
        return await convert_via_file_to_markdown(Path(file_path), **kwargs)
