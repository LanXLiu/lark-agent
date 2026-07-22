"""
Excel 表格转换器（薄封装）。

由 ``file_to_markdown.structured_exporters`` 将各 Sheet 转为 Markdown 表格。
"""

from pathlib import Path

from knowledge.ingestion.converter.base import BaseConverter, ConversionResult, convert_via_file_to_markdown


class ExcelConverter(BaseConverter):
    """``.xlsx`` / ``.xls`` → Markdown 表格。"""

    supported_extensions = (".xlsx", ".xls")

    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        Args:
            file_path: Excel 文件路径。
            **kwargs: 预留扩展参数。

        Returns:
            ``ConversionResult``。
        """
        return await convert_via_file_to_markdown(Path(file_path), **kwargs)
