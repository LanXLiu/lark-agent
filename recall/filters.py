"""将业务过滤条件转换为 Qdrant Filter。"""

from __future__ import annotations

from qdrant_client.http import models


def build_extra_filter(
    *,
    doc_uuid: str | None = None,
    doc_type: str | None = None,
    filename: str | None = None,
    tags: list[str] | None = None,
) -> models.Filter | None:
    """构建附加 must 条件（软删由 QdrantClient._base_filter 统一处理）。"""
    must: list[models.Condition] = []

    if doc_uuid:
        must.append(
            models.FieldCondition(
                key="doc_uuid",
                match=models.MatchValue(value=doc_uuid),
            )
        )
    if doc_type:
        must.append(
            models.FieldCondition(
                key="doc_type",
                match=models.MatchValue(value=doc_type),
            )
        )
    if filename:
        must.append(
            models.FieldCondition(
                key="filename",
                match=models.MatchValue(value=filename),
            )
        )
    if tags:
        for tag in tags:
            tag = str(tag).strip()
            if tag:
                must.append(
                    models.FieldCondition(
                        key="tags",
                        match=models.MatchValue(value=tag),
                    )
                )

    if not must:
        return None
    return models.Filter(must=must)
