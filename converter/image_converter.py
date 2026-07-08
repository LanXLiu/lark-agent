"""
栅格图像转换器（薄封装）。

由 ``file_to_markdown.image_to_markdown`` 使用 PP-Structure 等管线生成 Markdown。
"""

from pathlib import Path

from converter.base import BaseConverter, ConversionResult, convert_via_file_to_markdown


class ImageConverter(BaseConverter):
    """常见图片后缀 → Markdown（OCR / 版式解析）。"""

    supported_extensions = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")

    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        Args:
            file_path: 图片路径。
            **kwargs: 透传统一入口可选参数。

        Returns:
            ``ConversionResult``。
        """
        return await convert_via_file_to_markdown(Path(file_path), **kwargs)
