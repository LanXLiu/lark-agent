"""Business database MCP server built on the official MCP Python SDK."""

from __future__ import annotations

from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from infrastructure.mcp.auth import ApiKeyGuard
from infrastructure.mcp.business import build_business_backend, execute_business_query
from infrastructure.mcp.config import env_csv, required_env, required_env_int


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
        "lark-agent-business-db",
        stateless_http=True,
        json_response=True,
        **transport_settings,
    )
    backend = build_business_backend()
    allowed = env_csv("BUSINESS_DB_MCP_ALLOW_TOOLS")

    def inventory_lookup(sku: str, warehouse_code: str | None = None) -> dict[str, Any]:
        """Query current inventory for one exact SKU, optionally in one warehouse."""
        return execute_business_query(backend, "inventory_lookup", locals())

    def inventory_batch_lookup(
        skus: list[str], warehouse_code: str | None = None
    ) -> dict[str, Any]:
        """Query current inventory for several exact SKU codes."""
        return execute_business_query(backend, "inventory_batch_lookup", locals())

    def order_status(order_no: str) -> dict[str, Any]:
        """Query the current state and milestones of an exact order number."""
        return execute_business_query(backend, "order_status", locals())

    def product_lookup(keyword: str, category: str | None = None) -> dict[str, Any]:
        """Find products by product name, SKU, or keyword."""
        return execute_business_query(backend, "product_lookup", locals())

    functions = {
        "inventory_lookup": inventory_lookup,
        "inventory_batch_lookup": inventory_batch_lookup,
        "order_status": order_status,
        "product_lookup": product_lookup,
    }
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
    return ApiKeyGuard(mcp_app, "BUSINESS_DB_MCP_API_KEY")


def main() -> None:
    host = required_env("BUSINESS_DB_MCP_HOST")
    port = required_env_int("BUSINESS_DB_MCP_PORT", maximum=65535)
    path = required_env("BUSINESS_DB_MCP_PATH")
    server = create_mcp_server(host=host, port=port, path=path)
    uvicorn.run(
        create_app(server),
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
