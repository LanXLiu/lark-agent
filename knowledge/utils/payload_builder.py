"""Chunk JSON → Qdrant PointStruct（含统一 payload 字段）。"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from qdrant_client.http import models

from knowledge.ingestion.chunker import ChunkResult
from infrastructure.db.qdrant import QdrantConfig, make_point_id


def build_chunk_payload_id(doc_uuid: str, chunk_index: int) -> str:
    """说明书约定的切片业务主键字符串。"""
    return f"{doc_uuid}_{chunk_index}"


def build_point_payload(
    *,
    doc_uuid: str,
    chunk: ChunkResult,
    doc_meta: dict[str, Any],
    tenant_id: str = "",
    tags: list[str] | None = None,
    is_deleted: bool = False,
    ext_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """组装 7 个 collection 通用的 payload 字段。"""
    meta = chunk.metadata or {}
    chunk_index = int(chunk.index)
    # breadcrumb 可能是 list（祖先标题列表）或字符串；统一成 "A > B > C" 字符串，
    # 便于父子召回按前缀过滤。
    raw_bc = meta.get("breadcrumb")
    if isinstance(raw_bc, (list, tuple)):
        breadcrumb = " > ".join(str(p) for p in raw_bc if p)
    else:
        breadcrumb = str(raw_bc or "")
    return {
        "id": build_chunk_payload_id(doc_uuid, chunk_index),
        "doc_uuid": doc_uuid,
        "chunk_index": chunk_index,
        "content": chunk.text,
        "token_count": int(chunk.token_count or len(chunk.text)),
        "source": doc_meta.get("source") or "",
        "markdown_key": doc_meta.get("markdown_key") or "",
        "filename": doc_meta.get("filename") or "",
        "converter": doc_meta.get("converter") or "unknown",
        "chunker_strategy": doc_meta.get("chunker_strategy") or "unknown",
        "doc_type": meta.get("doc_type") or doc_meta.get("doc_type") or "",
        "title": meta.get("title") or meta.get("breadcrumb", [""])[-1] if meta.get("breadcrumb") else "",
        "breadcrumb": breadcrumb,
        "level": int(meta.get("level") or 0),
        "page": meta.get("page"),
        "sheet": meta.get("sheet"),
        "chunk_kind": meta.get("chunk_kind") or meta.get("kind") or "",
        "record_index": meta.get("record_index"),
        "row_index": meta.get("row_index"),
        "part_index": meta.get("part_index"),
        "tenant_id": tenant_id,
        "tags": list(tags or []),
        "is_deleted": bool(is_deleted),
        # ext_info 自动兜底整个 chunk metadata：以后新增任何 metadata 字段都会入库，
        # 无需再手动维护上面的字段白名单。
        "ext_info": {**dict(meta), **(ext_info or {})},
    }


def build_point_struct(
    *,
    config: QdrantConfig,
    doc_uuid: str,
    chunk: ChunkResult,
    dense_vector: list[float],
    sparse_vector: models.SparseVector | None,
    doc_meta: dict[str, Any],
    tenant_id: str = "",
    tags: list[str] | None = None,
) -> models.PointStruct:
    """构造可 upsert 的 PointStruct（named dense + sparse）。"""
    chunk_index = int(chunk.index)
    point_id = make_point_id(config, doc_uuid, chunk_index)
    payload = build_point_payload(
        doc_uuid=doc_uuid,
        chunk=chunk,
        doc_meta=doc_meta,
        tenant_id=tenant_id,
        tags=tags,
        is_deleted=False,
    )
    vector: dict[str, Any] = {config.dense_vector_name: dense_vector}
    if sparse_vector is not None:
        vector[config.sparse_vector_name] = sparse_vector
    return models.PointStruct(id=point_id, vector=vector, payload=payload)


def chunk_dict_to_result(item: dict[str, Any]) -> ChunkResult:
    """将 MinIO chunk JSON 中的单条记录还原为 ChunkResult。"""
    return ChunkResult(
        text=str(item.get("text") or ""),
        index=int(item.get("index", 0)),
        token_count=int(item.get("token_count") or 0),
        metadata=dict(item.get("metadata") or {}),
    )
