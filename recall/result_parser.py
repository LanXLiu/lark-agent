"""Qdrant 检索结果 → RecallHit。"""

from __future__ import annotations

from typing import Any

from recall.schemas import RecallHit


def parse_scored_point(point: Any, *, collection: str) -> RecallHit:
    payload = dict(point.payload or {})
    chunk_index = payload.get("chunk_index")
    try:
        chunk_index_int = int(chunk_index) if chunk_index is not None else 0
    except (TypeError, ValueError):
        chunk_index_int = 0

    tags = payload.get("tags")
    if not isinstance(tags, list):
        tags = []

    rrf_score = float(point.score or 0.0)
    return RecallHit(
        id=str(payload.get("id") or point.id),
        score=rrf_score,
        recall_score=rrf_score,
        rerank_score=None,
        content=str(payload.get("content") or ""),
        doc_uuid=str(payload.get("doc_uuid") or ""),
        chunk_index=chunk_index_int,
        collection=collection,
        title=str(payload.get("title") or ""),
        source=str(payload.get("source") or ""),
        markdown_key=str(payload.get("markdown_key") or ""),
        filename=str(payload.get("filename") or ""),
        converter=str(payload.get("converter") or ""),
        chunker_strategy=str(payload.get("chunker_strategy") or ""),
        doc_type=str(payload.get("doc_type") or ""),
        breadcrumb=str(payload.get("breadcrumb") or ""),
        level=int(payload.get("level") or 0),
        page=payload.get("page"),
        sheet=payload.get("sheet"),
        chunk_kind=str(payload.get("chunk_kind") or ""),
        tenant_id=str(payload.get("tenant_id") or ""),
        tags=[str(t) for t in tags],
        token_count=int(payload.get("token_count") or 0),
        ext_info=dict(payload.get("ext_info") or {}),
    )
