"""工具注册表：@register_tool 收集工具，导出 TOOL_SCHEMAS，按名分发 execute。

加新工具 = 写一个带 name/description/parameters/run 的类,打 @register_tool,
再在本模块底部 import 触发注册即可,主图(graph.py)无需改动。
"""

from __future__ import annotations

from typing import Any

from service.agent.tools.base import Tool, ToolContext, ToolResult, to_openai_schema

# name -> Tool 实例
_REGISTRY: dict[str, Tool] = {}
# 不暴露给 LLM 的「内部工具」——由代码在特定时机主动调用(如降级联网)，
# 不进 tool_schemas，避免 LLM 平级乱选(web_search 走知识库不足时的降级触发)。
_INTERNAL_TOOLS: set[str] = {"web_search"}


def register_tool(cls):
    """类装饰器：实例化并按 name 注册。用法见 search.py / clock.py。"""
    instance = cls()
    _REGISTRY[instance.name] = instance
    return cls


def tool_schemas() -> list[dict[str, Any]]:
    """暴露给 LLM 的 OpenAI tools 数组(不含内部工具，如降级用的 web_search)。"""
    return [
        to_openai_schema(t)
        for name, t in _REGISTRY.items()
        if name not in _INTERNAL_TOOLS
    ]


def execute(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    """按名执行工具。未知工具/执行异常都回一段文本让 LLM 自行处理,不抛。"""
    tool = _REGISTRY.get(name)
    if tool is None:
        return ToolResult(text=f"[错误：未知工具 {name}]")
    try:
        return tool.run(args or {}, ctx)
    except Exception as exc:  # noqa: BLE001 —— 单个工具失败不应中断 Agent
        return ToolResult(text=f"[工具 {name} 执行失败：{exc}]")


# 触发各工具模块的 @register_tool 副作用(import 即注册)
from service.agent.tools import clock as _clock  # noqa: E402,F401
from service.agent.tools import search as _search  # noqa: E402,F401
from service.agent.tools import web_search as _web_search  # noqa: E402,F401
