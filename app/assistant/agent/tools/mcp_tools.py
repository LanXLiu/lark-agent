"""Agent-side proxies for the business database MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.assistant.agent.tools.business_guards import enforce_business_query_guards
from app.assistant.agent.tools.base import ToolContext, ToolResult
from app.assistant.agent.tools.registry import register_tool_instance
from infrastructure.mcp.business import BUSINESS_TOOLS
from infrastructure.mcp.client import McpHttpClient
from infrastructure.mcp.config import env_bool, env_csv, required_env_float


@dataclass
class McpProxyTool:
    name: str
    description: str
    parameters: dict[str, Any]
    url_env: str
    api_key_env: str
    timeout_env: str
    permission_group: str | None = None

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        if self.permission_group == "business_db":
            enforce_business_query_guards(self.name, args, ctx)
        client = McpHttpClient(
            os.getenv(self.url_env, "").strip(),
            os.getenv(self.api_key_env, "").strip(),
            required_env_float(self.timeout_env),
        )
        result = client.call_tool(self.name, args)
        return ToolResult(text=client.result_text(result))


def _register_business_tools() -> None:
    if not env_bool("MCP_ENABLED"):
        return
    allowed = env_csv("BUSINESS_DB_MCP_ALLOW_TOOLS")
    for name, definition in BUSINESS_TOOLS.items():
        if name not in allowed:
            continue
        register_tool_instance(
            McpProxyTool(
                name=name,
                description=definition["description"],
                parameters=definition["inputSchema"],
                url_env="BUSINESS_DB_MCP_URL",
                api_key_env="BUSINESS_DB_MCP_API_KEY",
                timeout_env="BUSINESS_DB_MCP_TIMEOUT_SECONDS",
                permission_group="business_db",
            )
        )


_register_business_tools()


def _register_web_fetch_tool() -> None:
    if not (env_bool("MCP_ENABLED") and env_bool("WEB_MCP_ENABLED")):
        return
    allowed = env_csv("WEB_MCP_ALLOW_TOOLS")
    if "web_fetch" not in allowed:
        return
    register_tool_instance(
        McpProxyTool(
            name="web_fetch",
            description="Read the main text from a public webpage URL returned by web search.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public http/https webpage URL"}
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            url_env="WEB_MCP_URL",
            api_key_env="WEB_MCP_API_KEY",
            timeout_env="WEB_MCP_TIMEOUT_SECONDS",
        )
    )


_register_web_fetch_tool()
