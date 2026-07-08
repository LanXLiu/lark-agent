"""查询文本编码：dense (BGE) + sparse (BM25)。"""

from __future__ import annotations

from qdrant_client.http import models

from db.qdrant import QdrantConfig
from model.embedding_client import EmbeddingClient
from utils.sparse_embedder import SparseEmbedder


class QueryEncoder:
    """与入库共用模型，保证 query / document 向量空间一致。"""

    def __init__(
        self,
        *,
        embedder: EmbeddingClient | None = None,
        sparse_embedder: SparseEmbedder | None = None,
        qdrant_config: QdrantConfig | None = None,
    ) -> None:
        cfg = qdrant_config or QdrantConfig.from_settings()
        self.embedder = embedder or EmbeddingClient()
        self.sparse_embedder = sparse_embedder or SparseEmbedder(cfg)
        self.dense_model_name = self.embedder.model
        self.sparse_model_name = self.sparse_embedder.model_name

    def encode(self, query: str) -> tuple[list[float], models.SparseVector]:
        text = (query or "").strip()
        if not text:
            raise ValueError("query 不能为空")
        dense = self.embedder.encode_query([text])[0]
        sparse = self.sparse_embedder.embed_query(text)
        return dense, sparse
