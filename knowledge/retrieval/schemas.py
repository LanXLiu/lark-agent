"""召回请求/响应数据结构（与 HTTP 层解耦）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecallRequest:
    """单库混合召回请求。"""

    query: str
    collection: str
    top_k: int = 10
    tenant_id: str | None = None
    doc_uuid: str | None = None
    doc_type: str | None = None
    filename: str | None = None
    tags: list[str] | None = None
    include_deleted: bool = False
    min_score: float | None = None
    enable_rerank: bool | None = None
    candidate_top_k: int | None = None
    # 单次覆盖父子召回开关：None 走全局 RecallConfig.parent_child_enabled，
    # True/False 则本次强制开/关（供 Agent 工具按问题类型自主决定是否带上下文）。
    parent_child: bool | None = None


@dataclass
class RecallHit:
    """单条召回切片。"""

    id: str
    score: float
    content: str
    doc_uuid: str
    chunk_index: int
    collection: str
    recall_score: float | None = None
    rerank_score: float | None = None
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
    tags: list[str] = field(default_factory=list)
    token_count: int = 0
    ext_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallResult:
    """召回结果。"""

    query: str
    collection: str
    hits: list[RecallHit]
    total: int
    latency_ms: float
    model_dense: str
    model_sparse: str
    model_rerank: str = ""
    rerank_enabled: bool = False
