"""
文档转换 API 的请求 / 响应模型。

各转换接口统一返回 ``ConvertResponse``：Markdown 正文 + 元数据字典。
"""

from typing import Any

from pydantic import BaseModel, Field


class ConvertResponse(BaseModel):
    """
    转换成功后的统一响应体。

    Attributes:
        markdown: 清洗后的 Markdown 全文。
        metadata: 转换器附加信息（如 ``converter``、``pdf_render_mode`` 等）。
        filename: 客户端上传时使用的原始文件名。
    """

    markdown: str = Field(..., description="转换得到的 Markdown")
    metadata: dict[str, Any] = Field(default_factory=dict, description="转换元数据")
    filename: str = Field(..., description="原始文件名")
