"""Synchronous facade over the official MCP Streamable HTTP client."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class McpToolCallError(RuntimeError):
    pass


class McpHttpClient:
    def __init__(self, url: str, api_key: str, timeout_seconds: float) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.url:
            raise McpToolCallError("MCP URL is not configured")
        try:
            return asyncio.run(self._call_tool(name, arguments))
        except McpToolCallError:
            raise
        except Exception as exc:
            raise McpToolCallError(f"MCP request failed: {exc}") from exc

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(headers=headers, timeout=timeout) as http_client:
            async with streamable_http_client(self.url, http_client=http_client) as streams:
                read_stream, write_stream, _ = streams
                async with ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=self.timeout_seconds),
                ) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments)
        body = result.model_dump(by_alias=True, exclude_none=True)
        if result.isError:
            raise McpToolCallError(self.result_text(body) or f"MCP tool {name} failed")
        return body

    @staticmethod
    def result_text(result: dict[str, Any]) -> str:
        text = "\n".join(
            str(item.get("text") or "")
            for item in result.get("content") or []
            if item.get("type") == "text"
        ).strip()
        if text:
            return text
        structured = result.get("structuredContent") or result.get("structured_content")
        return str(structured) if structured is not None else ""
