"""
Word（DOCX）文档转换器（薄封装）。

由 ``file_to_markdown`` 中 Word 管线完成 mammoth/HTML 与可选内嵌图 OCR。
"""

from pathlib import Path

from knowledge.ingestion.converter.base import BaseConverter, ConversionResult, convert_via_file_to_markdown


class DocxConverter(BaseConverter):
    """DOCX → Markdown，统一走 ``convert_via_file_to_markdown``。"""

    supported_extensions = (".docx",)

    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        Args:
            file_path: ``.docx`` 路径。
            **kwargs: 如 ``enable_word_ocr``。

        Returns:
            ``ConversionResult``。
        """
        return await convert_via_file_to_markdown(Path(file_path), **kwargs)
