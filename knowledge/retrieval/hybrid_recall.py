"""混合召回（dense + BM25 sparse，Qdrant RRF 融合）+ 可选 Cross-Encoder 精排。"""

from __future__ import annotations

import asyncio
import time

from loguru import logger

from infrastructure.db.qdrant import QdrantClient, get_qdrant_client
from infrastructure.model.rerank_client import RerankClient
from knowledge.retrieval.config import RecallConfig
from knowledge.retrieval.filters import build_extra_filter
from knowledge.retrieval.postprocess import apply_postprocess
from knowledge.retrieval.query_encoder import QueryEncoder
from knowledge.retrieval.rerank_stage import apply_rerank
from knowledge.retrieval.result_parser import parse_scored_point
from knowledge.retrieval.schemas import RecallRequest, RecallResult


class HybridRecaller:
    """单 collection 混合召回入口。"""

    def __init__(
        self,
        *,
        qdrant: QdrantClient | None = None,
        encoder: QueryEncoder | None = None,
        reranker: RerankClient | None = None,
        config: RecallConfig | None = None,
    ) -> None:
        self.qdrant = qdrant or get_qdrant_client()
        self.qdrant_config = self.qdrant.config
        self.encoder = encoder or QueryEncoder(qdrant_config=self.qdrant_config)
        self.reranker = reranker or RerankClient()
        self.config = config or RecallConfig.from_settings()

    def search(self, request: RecallRequest) -> RecallResult:
        self._validate_request(request)
        started = time.perf_counter()
        use_rerank = self._use_rerank(request)
        final_top_k = self.config.effective_top_k(request.top_k)
        qdrant_limit = (
            self.config.effective_candidate_top_k(final_top_k, request.candidate_top_k)
            if use_rerank
            else final_top_k
        )

        dense, sparse = self.encoder.encode(request.query)
        extra_filter = build_extra_filter(
            doc_uuid=request.doc_uuid,
            doc_type=request.doc_type,
            filename=request.filename,
            tags=request.tags,
        )

        response = self.qdrant.hybrid_search(
            collection_name=request.collection,
            query_dense=dense,
            query_sparse=sparse,
            limit=qdrant_limit,
            tenant_id=request.tenant_id,
            extra_filter=extra_filter,
        )

        points = getattr(response, "points", None) or []
        hits = [parse_scored_point(p, collection=request.collection) for p in points]

        if use_rerank and hits:
            hits = apply_rerank(request.query, hits, self.reranker)

        if use_rerank:
            min_score = (
                request.min_score
                if request.min_score is not None
                else self.config.rerank_min_score
            )
        else:
            min_score = (
                request.min_score
                if request.min_score is not None
                else self.config.min_score
            )

        hits = apply_postprocess(
            hits,
            min_score=min_score,
            max_hits_per_doc=self.config.max_hits_per_doc,
        )
        hits = hits[:final_top_k]

        # 父子扩展：把每个命中 chunk 的「同父路径兄弟」一并带出，
        # 让问「第四层」能返回其下 L1~L5。扩展的 chunk 仅作上下文补充，不参与 rerank。
        if self._use_parent_child(request):
            hits = self._expand_siblings(hits, request)

        _log_hits(request.query, hits)

        latency_ms = (time.perf_counter() - started) * 1000.0
        return RecallResult(
            query=request.query,
            collection=request.collection,
            hits=hits,
            total=len(hits),
            latency_ms=round(latency_ms, 2),
            model_dense=self.encoder.dense_model_name,
            model_sparse=self.encoder.sparse_model_name,
            model_rerank=self.reranker.model if use_rerank else "",
            rerank_enabled=use_rerank,
        )

    async def asearch(self, request: RecallRequest) -> RecallResult:
        return await asyncio.to_thread(self.search, request)

    def _expand_siblings(self, hits: list, request: RecallRequest) -> list:
        """对**高分**命中 chunk，把同 doc_uuid + 同父路径(breadcrumb 去掉末段)的
        兄弟 chunk 补进结果，让问「第四层」能带出 L1~L5。

        只对高分命中扩展（避免低分噪音命中也拖出一整组兄弟）：
        取最高分命中分数为基准，只对 score >= 基准 * 比例 的命中做扩展。
        每个父路径组最多补 max_siblings 条；扩展项不参与 rerank，
        按原文顺序(chunk_index)排。已在结果里的 (doc_uuid, chunk_index) 去重。
        """
        if not hits:
            return hits

        max_sib = self.config.parent_child_max_siblings
        # 只对「最高分」那一档命中扩展：分数必须非常接近 top（同一档），
        # 避免分数相近但属不同章节的次高命中也拖出整组兄弟。
        top_score = max((h.score for h in hits), default=0.0)
        # 用绝对差而非比例：与最高分相差 < 0.02 才算同一档（更严，防招式/场景串入）
        expand_margin = 0.02

        seen: set[tuple[str, int]] = {(h.doc_uuid, h.chunk_index) for h in hits}
        # 已处理过的父路径，避免多个命中同属一组时重复查询
        done_groups: set[tuple[str, str]] = set()
        extras: list = []

        for hit in list(hits):
            if hit.score < top_score - expand_margin:
                continue  # 非最高分档命中不扩展，避免拖出无关章节
            bc = (hit.breadcrumb or "").strip()
            if not bc or " > " not in bc:
                continue  # 无 breadcrumb 或本身是顶层，无父路径可扩展
            parent_path = bc.rsplit(" > ", 1)[0]  # 去掉自身末段 = 父路径
            group_key = (hit.doc_uuid, parent_path)
            if group_key in done_groups:
                continue
            done_groups.add(group_key)

            try:
                records = self.qdrant.scroll_siblings(
                    request.collection,
                    doc_uuid=hit.doc_uuid,
                    breadcrumb_prefix=parent_path,
                    tenant_id=request.tenant_id,
                    limit=max_sib * 3,  # 多拉点，去重/截断后保证够 max_sib
                )
            except Exception as exc:  # noqa: BLE001 —— 扩展失败不影响主结果
                logger.warning("父子扩展查询失败 doc_uuid={} parent={!r}: {}",
                               hit.doc_uuid, parent_path, exc)
                continue

            added = 0
            for rec in records:
                if added >= max_sib:
                    break
                sib = parse_scored_point(_record_as_point(rec), collection=request.collection)
                key = (sib.doc_uuid, sib.chunk_index)
                if key in seen:
                    continue
                # 只要真正同父路径的（前缀匹配可能误含更深层，这里严格校验父路径）
                sib_bc = (sib.breadcrumb or "").strip()
                if not sib_bc.startswith(parent_path):
                    continue
                seen.add(key)
                sib.score = 0.0          # 扩展项不参与排序竞争
                sib.rerank_score = None
                extras.append(sib)
                added += 1

        if not extras:
            return hits

        # 合并后按 (doc_uuid, chunk_index) 排序，保持同文档内原文顺序
        merged = hits + extras
        merged.sort(key=lambda h: (h.doc_uuid, h.chunk_index))
        return merged

    def _use_rerank(self, request: RecallRequest) -> bool:
        if request.enable_rerank is not None:
            return bool(request.enable_rerank)
        return self.config.rerank_enabled

    def _use_parent_child(self, request: RecallRequest) -> bool:
        if request.parent_child is not None:
            return bool(request.parent_child)
        return self.config.parent_child_enabled

    def _validate_request(self, request: RecallRequest) -> None:
        collection = (request.collection or "").strip()
        if not collection:
            raise ValueError("collection 不能为空")
        if collection not in self.qdrant_config.collections:
            allowed = ", ".join(self.qdrant_config.collections)
            raise ValueError(f"不支持的 collection={collection!r}，允许值: {allowed}")
        if not (request.query or "").strip():
            raise ValueError("query 不能为空")


def get_hybrid_recaller() -> HybridRecaller:
    return HybridRecaller()


class _PointLike:
    """把 scroll 返回的 Record 适配成 parse_scored_point 需要的 point（带 score=0）。"""

    __slots__ = ("id", "payload", "score")

    def __init__(self, record) -> None:
        self.id = getattr(record, "id", None)
        self.payload = getattr(record, "payload", None) or {}
        self.score = 0.0


def _record_as_point(record):
    return _PointLike(record)


def _log_hits(query: str, hits: list, *, preview_chars: int = 150) -> None:
    """把召回（含 rerank 后）的最终片段打印到终端，便于排查与调阈值。"""
    logger.info("召回结果 query={!r} 命中={} 条", query, len(hits))
    for i, h in enumerate(hits, start=1):
        rerank = getattr(h, "rerank_score", None)
        recall = getattr(h, "recall_score", None)
        score = getattr(h, "score", 0.0)
        content = (getattr(h, "content", "") or "").replace("\n", " ")
        if len(content) > preview_chars:
            content = content[:preview_chars] + "…"
        logger.info(
            "  [{}] score={:.4f} rerank={} recall={} 文件={!r} 段落={}\n      {}",
            i,
            score,
            f"{rerank:.4f}" if rerank is not None else "-",
            f"{recall:.4f}" if recall is not None else "-",
            getattr(h, "filename", ""),
            getattr(h, "chunk_index", ""),
            content,
        )
