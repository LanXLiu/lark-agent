"""web_search 工具：Tavily 联网搜索（知识库召回不足时的降级补充源）。

作用：企业知识库里没有相关内容时，作为「外部知识补充」联网查公开资料
（如通用领域知识、行业动态）。定位上是 CRAG 式的「检索不足 → 外部纠正」。

数据主权说明：联网会把 query 发给外部服务（Tavily），与「资料不出私有边界」
的定位有张力，故由 RAG_ENABLE_WEB_SEARCH 开关控制；未配 TAVILY_API_KEY 时
优雅降级为「不可用」，不影响主流程。返回来源 title/url，供答案标注「来源：联网搜索」。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from service.agent.tools.base import ToolContext, ToolResult
from service.agent.tools.registry import register_tool

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 20.0
_CONTENT_MAX_CHARS = 800  # 单条网页内容截断，避免喂给 LLM 的上下文过长


@register_tool
class WebSearchTool:
    name = "web_search"
    description = (
        "联网搜索公开的通用领域知识 / 行业动态 / 时事。"
        "仅当企业知识库(search_knowledge)确实查不到、而问题属于公开常识时使用；"
        "涉及公司内部制度、流程、文档的问题必须用 search_knowledge，不要用本工具。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "联网搜索关键词"},
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(text="[错误：web_search 需要 query 参数]")

        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            # 优雅降级：未配置 key 时不可用，但不崩溃，如实告知 LLM。
            return ToolResult(text="[联网搜索不可用：未配置 TAVILY_API_KEY]")

        try:
            payload = {
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "include_answer": True,
                "max_results": 5,
            }
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.post(_TAVILY_URL, json=payload)
            if resp.status_code != 200:
                return ToolResult(text=f"[联网搜索失败：HTTP {resp.status_code}]")
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 —— 联网失败不应中断问答
            return ToolResult(text=f"[联网搜索失败：{exc}]")

        results = data.get("results") or []
        web_sources: list[dict[str, str]] = []
        blocks: list[str] = []
        answer = (data.get("answer") or "").strip()
        if answer:
            blocks.append(f"[联网摘要] {answer}")
        for i, item in enumerate(results, start=1):
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "")[:_CONTENT_MAX_CHARS].strip()
            web_sources.append({"title": title, "url": url})
            blocks.append(f"[网页{i}] {title}\n{content}")

        if not blocks:
            return ToolResult(text="联网未搜索到相关内容。")
        return ToolResult(text="\n\n".join(blocks), web_sources=web_sources)
