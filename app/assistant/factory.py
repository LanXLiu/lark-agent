"""Composition root for the agent assistant runtime.

Channel adapters should build the runtime here instead of knowing how the LLM,
retrieval service, and agent graph are wired together.
"""

from __future__ import annotations

from typing import Protocol

from knowledge.retrieval import HybridRecaller
from app.assistant.agent.graph import AgentService
from app.assistant.llm_client import BailianChatClient


class AgentRuntimeSettings(Protocol):
    bailian_api_key: str
    bailian_base_url: str
    bailian_model: str
    bailian_timeout_seconds: float
    rag_collections: list[str]
    rag_collection: str
    rag_top_k: int
    rag_enable_rerank: bool
    rag_candidate_top_k: int
    rag_max_tool_rounds: int
    rag_recall_quality_min: float
    rag_enable_web_search: bool


def build_agent_service(settings: AgentRuntimeSettings) -> AgentService:
    """Build the shared agent service from application settings."""
    llm_client = BailianChatClient(
        api_key=settings.bailian_api_key,
        base_url=settings.bailian_base_url,
        model=settings.bailian_model,
        timeout_seconds=settings.bailian_timeout_seconds,
    )
    return AgentService(
        llm_client=llm_client,
        recaller=HybridRecaller(),
        collections=settings.rag_collections or [settings.rag_collection],
        top_k=settings.rag_top_k,
        enable_rerank=settings.rag_enable_rerank,
        candidate_top_k=settings.rag_candidate_top_k,
        max_tool_rounds=settings.rag_max_tool_rounds,
        recall_quality_min=settings.rag_recall_quality_min,
        enable_web_search=settings.rag_enable_web_search,
    )


__all__ = ["AgentRuntimeSettings", "AgentService", "build_agent_service"]
