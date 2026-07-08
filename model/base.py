"""
模型客户端抽象基类与通用响应结构。

``LLMClient`` 等实现 ``BaseModelClient``，统一封装 HTTP 请求与响应解析。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelResponse:
    """
    对话类模型的一次返回结果。

    Attributes:
        content: 助手回复正文。
        model_name: 服务端返回的模型标识。
        usage: Token 等用量字典（结构依上游 API）。
        extra: 扩展字段，预留自定义数据。
    """

    content: str
    model_name: str
    usage: dict[str, int] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


class BaseModelClient(ABC):
    """
    模型 HTTP 客户端抽象基类。

    子类实现 ``_call_api``，将上游 JSON 映射为 ``ModelResponse`` 或等价结构。
    """

    @abstractmethod
    async def _call_api(self, payload: dict[str, Any]) -> ModelResponse:
        """
        发起一次模型请求并解析结果。

        Args:
            payload: 已序列化为 API 所需字段的字典。

        Returns:
            结构化的 ``ModelResponse``。
        """
        ...
