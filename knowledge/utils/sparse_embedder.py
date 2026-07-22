"""fastembed BM25 sparse 向量编码（懒加载单例）。"""

from __future__ import annotations

import threading
from typing import Any

from loguru import logger
from qdrant_client.http import models

from infrastructure.db.qdrant import QdrantConfig

_FASTEMBED_INSTALL_HINT = (
    "chunk->Qdrant 依赖 fastembed（BM25 sparse 向量）。请在当前 Python 环境安装：\n"
    "  pip install 'fastembed>=0.6.0'\n"
    "或安装项目全部依赖：\n"
    "  pip install -r requirements.txt"
)


def ensure_fastembed_installed() -> None:
    """启动向量化前检查 fastembed 是否已安装。"""
    try:
        import fastembed  # noqa: F401
    except ImportError as exc:
        raise ImportError(_FASTEMBED_INSTALL_HINT) from exc


class SparseEmbedder:
    _lock = threading.Lock()
    _model: Any = None
    _model_name: str | None = None

    def __init__(self, config: QdrantConfig | None = None) -> None:
        self.config = config or QdrantConfig.from_settings()
        self.model_name = self.config.sparse_model

    def _ensure_loaded(self) -> None:
        if SparseEmbedder._model is not None and SparseEmbedder._model_name == self.model_name:
            return
        with SparseEmbedder._lock:
            if SparseEmbedder._model is not None and SparseEmbedder._model_name == self.model_name:
                return
            try:
                from fastembed import SparseTextEmbedding
            except ImportError as exc:
                raise ImportError(_FASTEMBED_INSTALL_HINT) from exc

            SparseEmbedder._model = SparseTextEmbedding(model_name=self.model_name)
            SparseEmbedder._model_name = self.model_name
            logger.info("Sparse BM25 模型已加载：{}", self.model_name)

    def embed_texts(self, texts: list[str]) -> list[models.SparseVector]:
        if not texts:
            return []
        self._ensure_loaded()
        vectors: list[models.SparseVector] = []
        for emb in SparseEmbedder._model.embed(texts):
            vectors.append(
                models.SparseVector(
                    indices=emb.indices.tolist(),
                    values=emb.values.tolist(),
                )
            )
        return vectors

    def embed_query(self, text: str) -> models.SparseVector:
        result = self.embed_texts([text])
        return result[0]
