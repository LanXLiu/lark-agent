"""
文本向量化 HTTP 接口。

使用 ``model.embedding_client.EmbeddingClient`` 调用 OpenAI 兼容 ``/embeddings``；
对外约定向量维度 **1024**，与返回结果校验一致。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from infrastructure.model import EmbeddingClient
from infrastructure.model.schemas.model_response import LLMUsage

from ..schemas.embedding import (
    EmbedBatchRequest,
    EmbedBatchResponse,
    EmbedSingleRequest,
    EmbedSingleResponse,
    TokenUsageOut,
)

router = APIRouter()

# 与当前嵌入服务（如 bge-m3 等 1024 维）对齐的向量维度
EMBEDDING_DIMENSION = 1024


def _usage_out(u: LLMUsage) -> TokenUsageOut:
    return TokenUsageOut(
        prompt_tokens=u.prompt_tokens,
        completion_tokens=u.completion_tokens,
        total_tokens=u.total_tokens,
    )


def _assert_vectors_dim(vectors: list[list[float]]) -> None:
    """校验每条向量长度均为 EMBEDDING_DIMENSION。"""
    for i, vec in enumerate(vectors):
        if len(vec) != EMBEDDING_DIMENSION:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"嵌入服务返回的向量维度为 {len(vec)}（第 {i + 1} 条），"
                    f"与本接口约定维度 {EMBEDDING_DIMENSION} 不一致，请检查 embedding 模型与配置。"
                ),
            )


@router.post(
    "/single",
    response_model=EmbedSingleResponse,
    summary="单条文本向量化",
    description="对一段文本生成一条 1024 维向量。底层使用 ``EmbeddingClient.embed``。",
)
async def embed_single(body: EmbedSingleRequest):
    """
    **请求体 JSON 示例**

    ```json
    { "text": "你好，知识库。" }
    ```
    """
    try:
        client = EmbeddingClient()
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    try:
        result = await client.embed(body.text.strip())
    finally:
        await client.close()

    _assert_vectors_dim([result.vector])
    return EmbedSingleResponse(
        dimension=EMBEDDING_DIMENSION,
        model=result.model,
        vector=result.vector,
        usage=_usage_out(result.usage),
    )


@router.post(
    "/batch",
    response_model=EmbedBatchResponse,
    summary="批量文本向量化",
    description="对多条文本生成多条 1024 维向量，顺序与输入一致。底层使用 ``EmbeddingClient.embed_batch``。",
)
async def embed_batch(body: EmbedBatchRequest):
    """
    **请求体 JSON 示例**

    ```json
    { "texts": ["第一条", "第二条"] }
    ```
    """
    try:
        client = EmbeddingClient()
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    try:
        result = await client.embed_batch(body.texts)
    finally:
        await client.close()

    _assert_vectors_dim(result.vectors)
    return EmbedBatchResponse(
        dimension=EMBEDDING_DIMENSION,
        model=result.model,
        vectors=result.vectors,
        usage=_usage_out(result.usage),
    )
