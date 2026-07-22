"""Search and webpage MCP server built on the official MCP Python SDK."""

from __future__ import annotations

from typing import Any, Literal

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from infrastructure.mcp.auth import ApiKeyGuard
from infrastructure.mcp.config import env_csv, required_env, required_env_int
from infrastructure.mcp.web import web_fetch as run_web_fetch
from infrastructure.mcp.web import web_search as run_web_search


def create_mcp_server(
    *, host: str | None = None, port: int | None = None, path: str | None = None
) -> FastMCP:
    transport_settings: dict[str, Any] = {}
    if host is not None:
        transport_settings["host"] = host
    if port is not None:
        transport_settings["port"] = port
    if path is not None:
        transport_settings["streamable_http_path"] = path
    server = FastMCP(
        "lark-agent-web",
        stateless_http=True,
        json_response=True,
        **transport_settings,
    )
    allowed = env_csv("WEB_MCP_ALLOW_TOOLS")

    def web_search(
        query: str,
        max_results: int = 5,
        search_depth: Literal["basic", "advanced"] = "basic",
    ) -> dict[str, Any]:
        """Search current public web information and return source URLs."""
        return run_web_search(locals())

    def web_fetch(url: str) -> dict[str, Any]:
        """Read the main text from a public webpage URL."""
        return run_web_fetch(locals())

    functions = {"web_search": web_search, "web_fetch": web_fetch}
    for name, function in functions.items():
        if name in allowed:
            server.add_tool(function, name=name, structured_output=True)
    return server


def create_app(server: FastMCP | None = None) -> Any:
    mcp_server = server or create_mcp_server()
    mcp_app = mcp_server.streamable_http_app()

    async def health(request: Request) -> JSONResponse:
        tools = await mcp_server.list_tools()
        return JSONResponse(
            {"status": "ok", "server": mcp_server.name, "tools": [tool.name for tool in tools]}
        )

    mcp_app.router.routes.insert(0, Route("/health", health, methods=["GET"]))
    return ApiKeyGuard(mcp_app, "WEB_MCP_API_KEY")


def main() -> None:
    host = required_env("WEB_MCP_HOST")
    port = required_env_int("WEB_MCP_PORT", maximum=65535)
    path = required_env("WEB_MCP_PATH")
    server = create_mcp_server(host=host, port=port, path=path)
    uvicorn.run(
        create_app(server),
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
