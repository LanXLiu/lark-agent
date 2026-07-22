"""召回结果后处理。"""

from __future__ import annotations

from knowledge.retrieval.schemas import RecallHit


def apply_postprocess(
    hits: list[RecallHit],
    *,
    min_score: float | None = 0.0,
    max_hits_per_doc: int = 0,
) -> list[RecallHit]:
    """按分数过滤，并可限制单文档命中条数。``min_score=None`` 表示不按分数过滤。"""
    if min_score is None:
        filtered = list(hits)
    else:
        filtered = [h for h in hits if h.score >= min_score]
    if max_hits_per_doc <= 0:
        return filtered

    per_doc: dict[str, int] = {}
    limited: list[RecallHit] = []
    for hit in filtered:
        key = hit.doc_uuid or hit.id
        count = per_doc.get(key, 0)
        if count >= max_hits_per_doc:
            continue
        per_doc[key] = count + 1
        limited.append(hit)
    return limited
