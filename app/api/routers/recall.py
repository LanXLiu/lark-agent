"""
混合召回 HTTP 接口（dense + BM25，单 collection）。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas.recall import RecallHitOut, RecallSearchRequest, RecallSearchResponse
from knowledge.retrieval import HybridRecaller, RecallRequest

router = APIRouter()

_recaller: HybridRecaller | None = None


def _get_recaller() -> HybridRecaller:
    global _recaller
    if _recaller is None:
        _recaller = HybridRecaller()
    return _recaller


@router.post(
    "/search",
    response_model=RecallSearchResponse,
    summary="混合召回",
    description="dense + BM25 混合检索（RRF），默认再经 BGE cross-encoder 精排。",
)
async def recall_search(body: RecallSearchRequest):
    """
    **请求示例**

    ```json
    {
      "query": "广州SDC 入库流程",
      "collection": "rules",
      "top_k": 5
    }
    ```
    """
    try:
        recaller = _get_recaller()
        result = await recaller.asearch(
            RecallRequest(
                query=body.query,
                collection=body.collection,
                top_k=body.top_k,
                tenant_id=body.tenant_id,
                doc_uuid=body.doc_uuid,
                doc_type=body.doc_type,
                filename=body.filename,
                tags=body.tags,
                min_score=body.min_score,
                enable_rerank=body.enable_rerank,
                candidate_top_k=body.candidate_top_k,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"召回失败: {e}") from e

    hits = [
        RecallHitOut(
            id=h.id,
            score=h.score,
            recall_score=h.recall_score,
            rerank_score=h.rerank_score,
            content=h.content,
            doc_uuid=h.doc_uuid,
            chunk_index=h.chunk_index,
            collection=h.collection,
            title=h.title,
            source=h.source,
            markdown_key=h.markdown_key,
            filename=h.filename,
            converter=h.converter,
            chunker_strategy=h.chunker_strategy,
            doc_type=h.doc_type,
            breadcrumb=h.breadcrumb,
            level=h.level,
            page=h.page,
            sheet=h.sheet,
            chunk_kind=h.chunk_kind,
            tenant_id=h.tenant_id,
            tags=h.tags,
            token_count=h.token_count,
            ext_info=h.ext_info,
        )
        for h in result.hits
    ]

    return RecallSearchResponse(
        query=result.query,
        collection=result.collection,
        total=result.total,
        latency_ms=result.latency_ms,
        model_dense=result.model_dense,
        model_sparse=result.model_sparse,
        model_rerank=result.model_rerank,
        rerank_enabled=result.rerank_enabled,
        hits=hits,
    )
