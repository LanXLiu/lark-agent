"""
向量化 API 的请求 / 响应模型。

约定向量维度为 **1024**（与常见 bge 系列及本项目配置对齐）；若上游返回长度不一致，路由层会返回 502。
"""

from pydantic import BaseModel, Field, field_validator


class EmbedBatchRequest(BaseModel):
    """批量向量化请求体。"""

    texts: list[str] = Field(
        ...,
        min_length=1,
        description="待编码文本列表，至少 1 条",
    )

    @field_validator("texts")
    @classmethod
    def strip_nonempty(cls, v: list[str]) -> list[str]:
        out = [t.strip() for t in v if t is not None and str(t).strip()]
        if not out:
            raise ValueError("texts 不能为空或仅含空白字符串")
        return out


class TokenUsageOut(BaseModel):
    """Token 用量（嵌入接口常用字段）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class EmbedBatchResponse(BaseModel):
    """批量向量化响应；``vectors`` 与 ``texts`` 顺序一致。"""

    dimension: int = Field(1024, description="向量维度（本接口固定为 1024）")
    model: str = Field(..., description="实际使用的嵌入模型名")
    vectors: list[list[float]] = Field(..., description="每条文本对应一条向量")
    usage: TokenUsageOut = Field(default_factory=TokenUsageOut)


class EmbedSingleRequest(BaseModel):
    """单条向量化请求体。"""

    text: str = Field(..., min_length=1, description="待编码的单段文本")


class EmbedSingleResponse(BaseModel):
    """单条向量化响应。"""

    dimension: int = Field(1024, description="向量维度（本接口固定为 1024）")
    model: str
    vector: list[float]
    usage: TokenUsageOut = Field(default_factory=TokenUsageOut)
