"""向量化客户端（远程，OpenAI 兼容 /embeddings 接口）。

只支持远程后端（百炼 text-embedding-v3 等 OpenAI 兼容网关）。检索场景下
query 与 passage 用同一接口编码，向量空间一致。

配置见 ``conf/config_local.yaml`` 的 ``MODELS.JobEmbed``：``url`` / ``api_key`` /
``model`` / ``dim`` / ``batch_size``。打网关的请求带 429/5xx 退避重试。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from conf.settings import settings
from model.schemas.model_response import BatchEmbeddingResult, EmbeddingResult, LLMUsage
from utils.retry import retry_call

EncodeMode = Literal["query", "passage"]


def _job_embed_cfg() -> dict[str, Any]:
    models = getattr(settings, "MODELS", None)
    if not isinstance(models, dict):
        return {}
    job = models.get("JobEmbed")
    return job if isinstance(job, dict) else {}


class EmbeddingClient:
    """远程嵌入客户端：``encode_query`` / ``encode_passage`` → 向量列表。"""

    def __init__(self, model: str | None = None):
        job = _job_embed_cfg()
        name = (
            model
            or str(job.get("model") or "").strip()
            or str(getattr(settings, "embedding_model", "") or "").strip()
        )
        if not name:
            raise RuntimeError("EmbeddingClient 需要 MODELS.JobEmbed.model（远程嵌入模型名）")
        self.model = name
        try:
            self.dim = int(
                job["dim"]
                if job.get("dim") is not None
                else int(getattr(settings, "embedding_dim", 1024))
            )
        except (TypeError, ValueError):
            self.dim = 1024

        self.api_key = str(job.get("api_key") or "").strip()
        self.url = str(job.get("url") or "").strip().rstrip("/")
        self.embed_batch_size = max(1, int(job.get("batch_size") or 12))

    def _embedding_endpoint(self) -> str:
        if not self.url:
            raise RuntimeError("embedding backend requires MODELS.JobEmbed.url")
        if self.url.endswith("/embeddings"):
            return self.url
        return f"{self.url}/embeddings"

    def _encode_remote(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("embedding backend requires MODELS.JobEmbed.api_key")

        vectors: list[list[float]] = []
        batch_size = min(self.embed_batch_size, 10)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        endpoint = self._embedding_endpoint()

        with httpx.Client(timeout=120) as client:
            for start in range(0, len(texts), batch_size):
                batch = [(t or "").strip() for t in texts[start : start + batch_size]]
                payload = {
                    "model": self.model,
                    "input": batch,
                    "dimensions": self.dim,
                }

                def _post(payload=payload) -> httpx.Response:
                    resp = client.post(endpoint, headers=headers, json=payload)
                    resp.raise_for_status()  # 抛 HTTPStatusError（带状态码），供 retry 判定
                    return resp

                response = retry_call(_post, what="百炼 embedding 请求")
                data = response.json()
                items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
                vectors.extend([list(item["embedding"]) for item in items])

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"remote embedding returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return vectors

    def _encode(self, texts: list[str], mode: EncodeMode = "passage") -> list[list[float]]:
        # 远程 text-embedding-v3 对 query / passage 用同一接口，无需区分。
        if not texts:
            return []
        return self._encode_remote([(t or "").strip() for t in texts])

    def encode_query(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, mode="query")

    def encode_passage(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts, mode="passage")

    async def embed(self, text: str, *, mode: EncodeMode = "passage") -> EmbeddingResult:
        vecs = await asyncio.to_thread(self._encode, [text], mode)
        return EmbeddingResult(vector=vecs[0], model=self.model, usage=LLMUsage())

    async def embed_batch(
        self,
        texts: list[str],
        *,
        mode: EncodeMode = "passage",
    ) -> BatchEmbeddingResult:
        vecs = await asyncio.to_thread(self._encode, texts, mode)
        return BatchEmbeddingResult(vectors=vecs, model=self.model, usage=LLMUsage())

    async def close(self) -> None:
        return None
