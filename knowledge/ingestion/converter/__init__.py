"""
文档转换包：工厂、基类与各格式薄封装。

对外导出 ``ConverterFactory`` 与 ``convert_via_file_to_markdown``，供管线与其它模块引用。
"""

from .base import BaseConverter, ConversionResult, convert_via_file_to_markdown
from .converter_factory import ConverterFactory
from .docx_converter import DocxConverter
from .excel_converter import ExcelConverter
from .image_converter import ImageConverter
from .json_converter import JsonConverter
from .pdf_converter import PdfConverter
from .pptx_converter import PptxConverter

__all__ = [
    "BaseConverter",
    "ConversionResult",
    "convert_via_file_to_markdown",
    "ConverterFactory",
    "PdfConverter",
    "DocxConverter",
    "PptxConverter",
    "ExcelConverter",
    "ImageConverter",
    "JsonConverter",
]
