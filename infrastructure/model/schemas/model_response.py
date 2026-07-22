"""
模型调用返回数据结构定义。

包含 LLM 用量、单条/批量向量嵌入结果等 dataclass，供 ``model`` 包各客户端统一返回类型。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMUsage:
    """
    Token 用量统计。

    与常见 OpenAI 风格 ``usage`` 字段对齐，便于日志与计费。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class EmbeddingResult:
    """
    单条文本的向量嵌入结果。

    Attributes:
        vector: 浮点向量列表。
        model: 实际使用的嵌入模型名。
        usage: 若服务端返回 token 统计则填入，否则为默认值。
    """

    vector: list[float]
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)


@dataclass
class BatchEmbeddingResult:
    """
    多条文本批量嵌入结果。

    Attributes:
        vectors: 与输入顺序一致的向量列表（依赖服务端 ``index`` 字段排序）。
        model: 模型名。
        usage: 整次请求的用量汇总。
    """

    vectors: list[list[float]]
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
