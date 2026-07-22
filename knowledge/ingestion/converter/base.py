"""
文档转换抽象层：结果结构与统一调度入口。

定义 ``ConversionResult``、``BaseConverter`` 及 ``convert_via_file_to_markdown``，
使各格式转换器薄封装 ``file_to_markdown`` 统一管线。
"""

from abc import ABC, abstractmethod
import asyncio
from pathlib import Path


class ConversionResult:
    """
    单次文档转换的输出载体。

    Attributes:
        markdown: 转换得到的 Markdown 正文。
        metadata: 转换器附加信息（如 PDF 渲染模式、页数等）。
    """

    def __init__(self, markdown: str, metadata: dict | None = None):
        self.markdown = markdown
        self.metadata = metadata or {}

    def __bool__(self) -> bool:
        """非空正文视为有效结果，便于 ``if result:`` 判断。"""
        return len(self.markdown.strip()) > 0


class BaseConverter(ABC):
    """
    各格式转换器抽象基类。

    子类声明 ``supported_extensions`` 并实现 ``convert``。
    """

    supported_extensions: tuple[str, ...] = ()

    @abstractmethod
    async def convert(self, file_path: Path, **kwargs) -> ConversionResult:
        """
        将本地文件转为 Markdown。

        Args:
            file_path: 源文件路径。
            **kwargs: 透传给底层统一入口（如 ``max_scanned_pages``）。

        Returns:
            ``ConversionResult``。
        """
        ...

    def validate(self, file_path: Path) -> bool:
        """
        校验文件存在且后缀在支持列表中。

        Args:
            file_path: 待校验路径。

        Returns:
            可转换则为 True。
        """
        if not file_path.exists():
            return False
        ext = file_path.suffix.lower()
        return ext in self.supported_extensions


async def convert_via_file_to_markdown(file_path: Path, **kwargs) -> ConversionResult:
    """
    在线程池中执行同步的 ``file_to_markdown.convert_file_to_markdown``，避免阻塞事件循环。

    Args:
        file_path: 源文件路径。
        **kwargs: 透传给统一转换入口。

    Returns:
        包装后的 ``ConversionResult``。
    """
    from knowledge.ingestion.file_to_markdown.unified_entry import convert_file_to_markdown

    path = Path(file_path)
    res = await asyncio.to_thread(convert_file_to_markdown, path, **kwargs)
    return ConversionResult(markdown=res.markdown, metadata=res.metadata)
