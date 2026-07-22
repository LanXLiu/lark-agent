"""
JSON 文件转换器（薄封装）。

由 ``file_to_markdown.json_to_markdown`` 将结构化数据转为可读 Markdown。
"""

from pathlib import Path

from knowledge.ingestion.converter.base import BaseConverter, ConversionResult, convert_via_file_to_markdown


class JsonConverter(BaseConverter):
    """``.json`` → 标题/表格混合 Markdown。"""

    supported_extensions = (".json",)

    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        Args:
            file_path: JSON 文件路径（UTF-8）。
            **kwargs: 预留扩展参数。

        Returns:
            ``ConversionResult``。
        """
        return await convert_via_file_to_markdown(Path(file_path), **kwargs)
