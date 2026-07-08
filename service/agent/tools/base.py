"""Agent 工具的抽象基类与运行时上下文。

设计参考 financial_rag 的 ToolBase：每个工具声明 name / description / parameters
(JSON Schema),实现 run(args, ctx)。工具的「说明书」(to_openai_schema)给 LLM，
「身份与后端依赖」(ToolContext)由代码注入、绝不进 schema。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from recall.schemas import RecallHit


@dataclass
class ToolContext:
    """执行工具时代码注入的运行时依赖与身份。绝不暴露给 LLM。

    - recaller / collections / top_k / ...：检索后端与参数(供 search_knowledge)；
    - collections：要检索的 collection 列表(多库检索，合并结果)；
    - user_open_id / chat_id：当前提问者身份(供需要按人/群隔离的工具)。
    """

    recaller: Any = None
    collections: list[str] = field(default_factory=list)
    top_k: int = 5
    enable_rerank: bool | None = None
    candidate_top_k: int | None = None
    user_open_id: str | None = None
    chat_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果。

    - text：回传给 LLM 的文本(工具的「观察结果」)；
    - hits：本次检索命中的知识库片段，供 Agent 拼「文档 › 小标题」来源(非检索类工具为空)。
    - web_sources：联网搜索来源(title/url 列表)，供 Agent 拼「来源：联网搜索」(仅联网工具有)。
    """

    text: str
    hits: list[RecallHit] = field(default_factory=list)
    web_sources: list[dict[str, str]] = field(default_factory=list)


class Tool(Protocol):
    """工具接口。实现方需提供 name / description / parameters / run。"""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema 的 parameters 部分

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


def to_openai_schema(tool: Tool) -> dict[str, Any]:
    """把一个 Tool 转成 OpenAI tools 数组里的一项。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
