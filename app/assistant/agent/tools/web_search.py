"""Public web search fallback, optionally routed through the web MCP service."""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.assistant.agent.tools.base import ToolContext, ToolResult
from app.assistant.agent.tools.registry import register_tool
from infrastructure.mcp.client import McpHttpClient
from infrastructure.mcp.config import env_bool, required_env_float

_CONTENT_MAX_CHARS = 800


@register_tool
class WebSearchTool:
    name = "web_search"
    description = (
        "Search current public information. Use it when the knowledge base cannot answer "
        "and the question is about public facts, not internal company information."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Public web search query"}},
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(text="[web_search requires a query]")

        if env_bool("MCP_ENABLED") and env_bool("WEB_MCP_ENABLED"):
            return self._run_mcp(query)
        return self._run_tavily(query)

    @staticmethod
    def _run_mcp(query: str) -> ToolResult:
        client = McpHttpClient(
            os.getenv("WEB_MCP_URL", "").strip(),
            os.getenv("WEB_MCP_API_KEY", ""),
                required_env_float("WEB_MCP_TIMEOUT_SECONDS"),
        )
        result = client.call_tool("web_search", {"query": query})
        structured = result.get("structuredContent") or {}
        sources = [
            {"title": str(item.get("title") or ""), "url": str(item.get("url") or "")}
            for item in structured.get("results") or []
        ]
        return ToolResult(text=client.result_text(result), web_sources=sources)

    @staticmethod
    def _run_tavily(query: str) -> ToolResult:
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            return ToolResult(text="[Web search unavailable: TAVILY_API_KEY is not configured]")
        api_url = os.getenv("TAVILY_API_URL", "").strip()
        if not api_url:
            return ToolResult(text="[Web search unavailable: TAVILY_API_URL is not configured]")
        try:
            response = httpx.post(
                api_url,
                json={
                    "api_key": api_key,
                    "query": query,
                    "search_depth": "basic",
                    "include_answer": True,
                    "max_results": 5,
                },
                timeout=20.0,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # A web failure must not terminate the answer flow.
            return ToolResult(text=f"[Web search failed: {exc}]")

        results = data.get("results") or []
        sources: list[dict[str, str]] = []
        blocks: list[str] = []
        answer = str(data.get("answer") or "").strip()
        if answer:
            blocks.append(f"[Web summary] {answer}")
        for index, item in enumerate(results, start=1):
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            content = str(item.get("content") or "")[:_CONTENT_MAX_CHARS].strip()
            sources.append({"title": title, "url": url})
            blocks.append(f"[Web result {index}] {title}\n{content}")
        if not blocks:
            return ToolResult(text="No relevant public web results found.")
        return ToolResult(text="\n\n".join(blocks), web_sources=sources)
