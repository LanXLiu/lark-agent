"""
知识库召回包：单库 dense + BM25 混合检索。

用法::

    from recall import HybridRecaller, RecallRequest

    recaller = HybridRecaller()
    result = recaller.search(
        RecallRequest(query="入库流程", collection="rules", top_k=5)
    )
"""

from recall.hybrid_recall import HybridRecaller, get_hybrid_recaller
from recall.schemas import RecallHit, RecallRequest, RecallResult

__all__ = [
    "HybridRecaller",
    "get_hybrid_recaller",
    "RecallRequest",
    "RecallResult",
    "RecallHit",
]
