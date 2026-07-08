"""Chunk JSON -> Qdrant upsert stage."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger

from chunker import ChunkResult
from db.qdrant import QdrantClient, get_qdrant_client, infer_collection
from model.embedding_client import EmbeddingClient
from orchestrator.pipeline_common import PipelineStageContext, StageResult
from utils.payload_builder import build_point_struct, chunk_dict_to_result
from utils.sparse_embedder import SparseEmbedder


class ChunkToQdrantStage:
    """读取 MinIO chunk JSON，向量化后写入对应 Qdrant collection。"""

    def __init__(
        self,
        context: PipelineStageContext,
        *,
        qdrant: QdrantClient | None = None,
        embedder: EmbeddingClient | None = None,
        sparse_embedder: SparseEmbedder | None = None,
        embed_batch_size: int = 32,
        tenant_id: str = "",
        tags: list[str] | None = None,
        collection: str | None = None,
    ) -> None:
        self.context = context
        self.qdrant = qdrant or get_qdrant_client()
        self.embedder = embedder or EmbeddingClient()
        self.sparse_embedder = sparse_embedder or SparseEmbedder(self.qdrant.config)
        self.embed_batch_size = max(1, int(embed_batch_size))
        self.tenant_id = tenant_id
        self.tags = list(tags or [])
        self.collection_override = collection

    async def run(
        self,
        raw_key: str,
        *,
        chunk_key: str | None = None,
        collection: str | None = None,
        tenant_id: str | None = None,
        tags: list[str] | None = None,
    ) -> StageResult:
        return await asyncio.to_thread(
            self._run_sync,
            raw_key,
            chunk_key,
            collection,
            tenant_id,
            tags,
        )

    def _run_sync(
        self,
        raw_key: str,
        chunk_key: str | None,
        collection: str | None,
        tenant_id: str | None,
        tags: list[str] | None,
    ) -> StageResult:
        obj = self.context.stat_source_object(raw_key)
        chunk_rec = self.context.markdown_to_chunk_index.get(raw_key)
        if chunk_key is None and not chunk_rec:
            raise RuntimeError(
                f"markdown_to_chunk metadata not found for {raw_key}; skip chunk_to_qdrant"
            )

        ck = chunk_key or chunk_rec.get("chunk_key") or self.context.build_chunk_key(raw_key)
        payload = json.loads(
            self.context.client.download_bytes(self.context.BUCKET, ck).decode("utf-8")
        )
        doc_uuid = str(payload.get("doc_uuid") or "")
        if not doc_uuid:
            raise ValueError(f"chunk JSON missing doc_uuid: {ck}")

        chunks = [chunk_dict_to_result(item) for item in payload.get("chunks") or []]
        if not chunks:
            logger.warning("chunk JSON 为空，跳过向量化 key={}", raw_key)
            return StageResult(source_key=raw_key, stage="chunk_to_qdrant", chunk_count=0)

        target_collection = (
            collection
            or self.collection_override
            or infer_collection(raw_key, self.qdrant.config)
        )
        self.qdrant.ensure_collection_schema(target_collection)

        doc_meta = {
            "source": payload.get("source") or raw_key,
            "markdown_key": payload.get("markdown_key")
            or chunk_rec.get("markdown_key")
            or self.context.get_markdown_key(raw_key),
            "filename": payload.get("filename") or obj.get("Key", raw_key).split("/")[-1],
            "converter": payload.get("converter") or self.context.get_converter(raw_key),
            "chunker_strategy": payload.get("chunker_strategy") or "unknown",
        }
        effective_tenant = tenant_id if tenant_id is not None else self.tenant_id
        effective_tags = tags if tags is not None else self.tags

        points = self._build_points(
            doc_uuid=doc_uuid,
            chunks=chunks,
            doc_meta=doc_meta,
            tenant_id=effective_tenant,
            tags=effective_tags,
        )
        self.qdrant.upsert_points(points, target_collection)

        self.context.record_vectorized(
            obj=obj,
            key=raw_key,
            chunk_key=ck,
            collection=target_collection,
            doc_uuid=doc_uuid,
            point_count=len(points),
            tenant_id=effective_tenant,
        )

        logger.info(
            "chunk_to_qdrant 完成 key={} collection={} points={}",
            raw_key,
            target_collection,
            len(points),
        )
        return StageResult(
            source_key=raw_key,
            stage="chunk_to_qdrant",
            chunk_key=ck,
            qdrant_collection=target_collection,
            chunk_count=len(points),
            converter=doc_meta.get("converter") or "unknown",
        )

    def _build_points(
        self,
        *,
        doc_uuid: str,
        chunks: list[ChunkResult],
        doc_meta: dict[str, Any],
        tenant_id: str,
        tags: list[str],
    ) -> list[Any]:
        from qdrant_client.http import models

        cfg = self.qdrant.config
        points: list[models.PointStruct] = []
        batch_size = self.embed_batch_size

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [c.text for c in batch]
            dense_vectors = self.embedder.encode_passage(texts)
            sparse_vectors = self.sparse_embedder.embed_texts(texts)
            for chunk, dense, sparse in zip(batch, dense_vectors, sparse_vectors):
                points.append(
                    build_point_struct(
                        config=cfg,
                        doc_uuid=doc_uuid,
                        chunk=chunk,
                        dense_vector=dense,
                        sparse_vector=sparse,
                        doc_meta=doc_meta,
                        tenant_id=tenant_id,
                        tags=tags,
                    )
                )
        return points
