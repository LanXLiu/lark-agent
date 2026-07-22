"""召回 API 请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from knowledge.utils.collection_router import DEFAULT_COLLECTIONS


class RecallSearchRequest(BaseModel):
    """混合召回请求体。"""

    query: str = Field(..., min_length=1, description="检索问题或关键词")
    collection: str = Field(
        ...,
        description="Qdrant collection，由调用方指定，如 rules / company",
    )
    top_k: int = Field(10, ge=1, le=100, description="返回条数上限")
    tenant_id: str | None = Field(None, description="租户 ID 过滤")
    doc_uuid: str | None = Field(None, description="限定单文档")
    doc_type: str | None = Field(None, description="文档类型过滤")
    filename: str | None = Field(None, description="文件名精确匹配")
    tags: list[str] | None = Field(None, description="标签过滤（全部需匹配）")
    min_score: float | None = Field(None, description="最低分数（精排后为 rerank 分）")
    enable_rerank: bool | None = Field(None, description="是否精排；默认读配置 recall.rerank.enabled")
    candidate_top_k: int | None = Field(
        None,
        ge=1,
        le=200,
        description="精排前从 Qdrant 拉取的候选条数",
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("query 不能为空")
        return s

    @field_validator("collection")
    @classmethod
    def validate_collection(cls, v: str) -> str:
        name = (v or "").strip()
        if not name:
            raise ValueError("collection 不能为空")
        if name not in DEFAULT_COLLECTIONS:
            allowed = ", ".join(DEFAULT_COLLECTIONS)
            raise ValueError(f"collection 必须是以下之一: {allowed}")
        return name


class RecallHitOut(BaseModel):
    id: str
    score: float
    recall_score: float | None = None
    rerank_score: float | None = None
    content: str
    doc_uuid: str
    chunk_index: int
    collection: str
    title: str = ""
    source: str = ""
    markdown_key: str = ""
    filename: str = ""
    converter: str = ""
    chunker_strategy: str = ""
    doc_type: str = ""
    breadcrumb: str = ""
    level: int = 0
    page: Any = None
    sheet: Any = None
    chunk_kind: str = ""
    tenant_id: str = ""
    tags: list[str] = Field(default_factory=list)
    token_count: int = 0
    ext_info: dict[str, Any] = Field(default_factory=dict)


class RecallSearchResponse(BaseModel):
    query: str
    collection: str
    total: int
    latency_ms: float
    model_dense: str
    model_sparse: str
    model_rerank: str = ""
    rerank_enabled: bool = False
    hits: list[RecallHitOut]
