"""召回结果 Cross-Encoder 精排。"""

from __future__ import annotations

import dataclasses

from model.rerank_client import RerankClient
from recall.schemas import RecallHit


def apply_rerank(
    query: str,
    hits: list[RecallHit],
    reranker: RerankClient,
) -> list[RecallHit]:
    """按 rerank 分数重排；``score`` 为精排分，原 RRF 分写入 ``recall_score``。"""
    if not hits:
        return []

    passages = [h.content for h in hits]
    rerank_scores = reranker.rerank(query, passages)

    reranked: list[RecallHit] = []
    for hit, rr_score in zip(hits, rerank_scores):
        # 用 replace 原样复制所有字段（含 breadcrumb/level 等），只改分数，
        # 避免手动列字段时漏掉新增字段。
        reranked.append(
            dataclasses.replace(
                hit,
                score=float(rr_score),
                recall_score=float(
                    hit.recall_score if hit.recall_score is not None else hit.score
                ),
                rerank_score=float(rr_score),
            )
        )

    reranked.sort(key=lambda h: h.score, reverse=True)
    return reranked
