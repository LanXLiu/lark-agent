"""
转换器工厂：按扩展名注册并实例化 ``BaseConverter`` 子类。

模块加载时注册 PDF、Office、图片、JSON 等内置实现，供管线 ``ConverterStep`` 使用。
"""

from pathlib import Path

from converter.base import BaseConverter
from converter.docx_converter import DocxConverter
from converter.excel_converter import ExcelConverter
from converter.image_converter import ImageConverter
from converter.json_converter import JsonConverter
from converter.pdf_converter import PdfConverter
from converter.pptx_converter import PptxConverter


class ConverterFactory:
    """
    扩展名 → 转换器类的注册表。

    通过 ``register`` 扩展新格式；``get_converter`` 按路径后缀返回无状态新实例。
    """

    _registry: dict[str, type[BaseConverter]] = {}

    @classmethod
    def register(cls, ext: str, converter_cls: type[BaseConverter]) -> None:
        """
        注册一种扩展名对应的转换器类。

        Args:
            ext: 小写扩展名，含点号，如 ``".pdf"``。
            converter_cls: 继承 ``BaseConverter`` 的类。
        """
        cls._registry[ext.lower()] = converter_cls

    @classmethod
    def get_converter(cls, file_path: Path) -> BaseConverter:
        """
        根据文件路径后缀创建转换器实例。

        Args:
            file_path: 源文件路径。

        Returns:
            新构造的 ``BaseConverter`` 子类实例。

        Raises:
            ValueError: 未注册的后缀。
        """
        ext = file_path.suffix.lower()
        converter_cls = cls._registry.get(ext)
        if converter_cls is None:
            raise ValueError(f"Unsupported file extension: {ext}. Supported: {list(cls._registry.keys())}")
        return converter_cls()

    @classmethod
    def supported_extensions(cls) -> list[str]:
        """
        列出当前已注册的全部扩展名。

        Returns:
            扩展名字符串列表。
        """
        return list(cls._registry.keys())


# 内置格式注册（与 ingest 管线、格式探测步骤保持一致）
ConverterFactory.register(".pdf", PdfConverter)
ConverterFactory.register(".docx", DocxConverter)
ConverterFactory.register(".pptx", PptxConverter)
ConverterFactory.register(".ppt", PptxConverter)
ConverterFactory.register(".xlsx", ExcelConverter)
ConverterFactory.register(".xls", ExcelConverter)
ConverterFactory.register(".png", ImageConverter)
ConverterFactory.register(".jpg", ImageConverter)
ConverterFactory.register(".jpeg", ImageConverter)
ConverterFactory.register(".tiff", ImageConverter)
ConverterFactory.register(".tif", ImageConverter)
ConverterFactory.register(".bmp", ImageConverter)
ConverterFactory.register(".webp", ImageConverter)
ConverterFactory.register(".json", JsonConverter)
