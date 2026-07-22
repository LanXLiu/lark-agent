"""Cross-Encoder 精排（远程，OpenAI 兼容 rerank 接口）。

只支持远程后端（百炼 qwen3-vl-rerank 等）。配置见 ``infrastructure/conf/config_local.yaml``
的 ``MODELS.JobRerank``：``rerank_url`` / ``rerank_apikey``（或 ``url`` /
``api_key``）/ ``model`` / ``batch_size`` / ``instruct``。打网关的请求带
429/5xx 退避重试。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from infrastructure.conf.settings import settings
from knowledge.utils.retry import retry_call


def _job_rerank_cfg() -> dict[str, Any]:
    models = getattr(settings, "MODELS", None)
    if not isinstance(models, dict):
        return {}
    job = models.get("JobRerank")
    return job if isinstance(job, dict) else {}


class RerankClient:
    """远程 cross-encoder 精排：``rerank(query, passages)`` → 与 passages 同序的分数列表。"""

    def __init__(self, model: str | None = None) -> None:
        job = _job_rerank_cfg()
        self.model = (model or str(job.get("model") or "").strip())
        if not self.model:
            raise RuntimeError("RerankClient 需要 MODELS.JobRerank.model（远程 rerank 模型名）")
        self.url = str(job.get("rerank_url") or job.get("url") or "").strip()
        self.api_key = str(job.get("rerank_apikey") or job.get("api_key") or "").strip()
        self.instruct = str(
            job.get("instruct")
            or "Given a web search query, retrieve relevant passages that answer the query."
        ).strip()
        self.batch_size = min(max(1, int(job.get("batch_size") or 8)), 100)

    def rerank(self, query: str, passages: list[str]) -> list[float]:
        """对 ``[query, passage_i]`` 打分，分数越高越相关。"""
        if not passages:
            return []
        query = (query or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        if not self.url:
            raise RuntimeError("rerank backend requires MODELS.JobRerank.rerank_url")
        if not self.api_key:
            raise RuntimeError("rerank backend requires MODELS.JobRerank.rerank_apikey")

        scores = [0.0] * len(passages)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120) as client:
            for start in range(0, len(passages), self.batch_size):
                batch = passages[start : start + self.batch_size]
                payload = {
                    "model": self.model,
                    "input": {
                        "query": {"text": query},
                        "documents": [{"text": (p or "").strip() or " "} for p in batch],
                    },
                    "parameters": {
                        "return_documents": False,
                        "top_n": len(batch),
                        "instruct": self.instruct,
                    },
                }

                def _post(payload=payload) -> httpx.Response:
                    resp = client.post(self.url, headers=headers, json=payload)
                    resp.raise_for_status()  # 抛 HTTPStatusError（带状态码），供 retry 判定
                    return resp

                response = retry_call(_post, what="百炼 rerank 请求")
                data = response.json()
                results = data.get("output", {}).get("results", [])
                for item in results:
                    local_index = int(item["index"])
                    scores[start + local_index] = float(item["relevance_score"])

        return scores

    async def arerank(self, query: str, passages: list[str]) -> list[float]:
        return await asyncio.to_thread(self.rerank, query, passages)
