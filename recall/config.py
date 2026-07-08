"""召回模块配置（读取 conf YAML）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from conf.settings import settings
from db.qdrant import QdrantConfig


@dataclass(frozen=True)
class RecallConfig:
    default_top_k: int = 10
    prefetch_limit: int = 20
    max_hits_per_doc: int = 0
    min_score: float = 0.0
    rerank_enabled: bool = True
    rerank_candidate_top_k: int = 50
    rerank_min_score: float | None = None
    parent_child_enabled: bool = True
    parent_child_max_siblings: int = 10

    @classmethod
    def from_settings(cls) -> "RecallConfig":
        recall: dict[str, Any] = getattr(settings, "recall", None) or {}
        if not isinstance(recall, dict):
            recall = {}

        hybrid = recall.get("hybrid_search")
        if not isinstance(hybrid, dict):
            hybrid = {}
        retriever = getattr(settings, "retriever", None) or {}
        if isinstance(retriever, dict):
            retriever_hybrid = retriever.get("hybrid_search") or {}
            if isinstance(retriever_hybrid, dict):
                hybrid = {**retriever_hybrid, **hybrid}

        post = recall.get("postprocess")
        if not isinstance(post, dict):
            post = {}

        rerank = recall.get("rerank")
        if not isinstance(rerank, dict):
            rerank = {}
        rerank_min = rerank.get("min_score")
        if rerank_min is not None:
            rerank_min_score: float | None = float(rerank_min)
        else:
            rerank_min_score = None

        qdrant = QdrantConfig.from_settings()
        prefetch = int(
            hybrid.get("prefetch_limit") or qdrant.hybrid_prefetch_limit or 20
        )

        pc = recall.get("parent_child")
        if not isinstance(pc, dict):
            pc = {}

        return cls(
            default_top_k=int(recall.get("default_top_k") or 10),
            prefetch_limit=prefetch,
            max_hits_per_doc=int(post.get("max_hits_per_doc") or 0),
            min_score=float(post.get("min_score") or 0.0),
            rerank_enabled=bool(rerank.get("enabled", True)),
            rerank_candidate_top_k=int(rerank.get("candidate_top_k") or 50),
            rerank_min_score=rerank_min_score,
            parent_child_enabled=bool(pc.get("enabled", True)),
            parent_child_max_siblings=int(pc.get("max_siblings") or 10),
        )

    def effective_top_k(self, top_k: int | None) -> int:
        return max(1, int(top_k or self.default_top_k))

    def effective_candidate_top_k(self, top_k: int, candidate_top_k: int | None) -> int:
        final_k = self.effective_top_k(top_k)
        cand = int(candidate_top_k or self.rerank_candidate_top_k)
        return max(final_k, cand)
