"""
PowerPoint 演示文稿转换器（薄封装）。

由 ``file_to_markdown.structured_exporters`` 按幻灯片与形状抽取文本与表格。
"""

from pathlib import Path

from knowledge.ingestion.converter.base import BaseConverter, ConversionResult, convert_via_file_to_markdown


class PptxConverter(BaseConverter):
    """``.pptx`` / ``.ppt`` → 分节 Markdown。"""

    supported_extensions = (".pptx", ".ppt")

    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        Args:
            file_path: 演示文稿路径。
            **kwargs: 预留扩展参数。

        Returns:
            ``ConversionResult``。
        """
        return await convert_via_file_to_markdown(Path(file_path), **kwargs)
