from __future__ import annotations

import json
import sqlite3

from starlette.testclient import TestClient
from mcp.types import LATEST_PROTOCOL_VERSION

from infrastructure.mcp.business import SqliteBusinessBackend
from infrastructure.mcp.servers.business_db import create_app as create_business_app
from infrastructure.mcp.servers.web_search import create_app as create_web_app

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
}


def _rpc(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def test_business_mcp_lists_only_allowed_tools(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOW_TOOLS", "inventory_lookup,order_status")
    with TestClient(
        create_business_app(), base_url="http://127.0.0.1:8000", headers=MCP_HEADERS
    ) as client:
        response = client.post("/mcp", json=_rpc("tools/list"))

    assert response.status_code == 200
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert names == ["inventory_lookup", "order_status"]


def test_business_mcp_requires_configured_api_key(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_MCP_API_KEY", "secret")
    with TestClient(
        create_business_app(), base_url="http://127.0.0.1:8000", headers=MCP_HEADERS
    ) as client:
        assert client.post("/mcp", json=_rpc("tools/list")).status_code == 401
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer secret"},
            json=_rpc("tools/list"),
        )
    assert response.status_code == 200


def test_web_mcp_exposes_two_focused_tools(monkeypatch):
    monkeypatch.setenv("WEB_MCP_ALLOW_TOOLS", "web_search,web_fetch")
    with TestClient(
        create_web_app(), base_url="http://127.0.0.1:8000", headers=MCP_HEADERS
    ) as client:
        response = client.post("/mcp", json=_rpc("tools/list"))

    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert names == ["web_search", "web_fetch"]


def test_unknown_tool_returns_mcp_tool_error():
    with TestClient(
        create_web_app(), base_url="http://127.0.0.1:8000", headers=MCP_HEADERS
    ) as client:
        response = client.post(
            "/mcp",
            json=_rpc("tools/call", {"name": "missing", "arguments": {}}),
        )

    result = response.json()["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Unknown tool: missing"


def test_sqlite_backend_uses_parameterized_query_and_read_only_connection(tmp_path):
    database = tmp_path / "business.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE inventory (sku TEXT, warehouse_code TEXT, available_quantity INTEGER)"
        )
        connection.execute("INSERT INTO inventory VALUES ('SKU-1', 'WH-A', 12)")
    config = tmp_path / "queries.json"
    config.write_text(
        json.dumps(
            {
                "queries": {
                    "inventory_lookup": (
                        "SELECT sku, warehouse_code, available_quantity FROM inventory "
                        "WHERE sku = :sku AND (:warehouse_code IS NULL OR warehouse_code = :warehouse_code)"
                    )
                }
            }
        ),
        encoding="utf-8",
    )
    backend = SqliteBusinessBackend(str(database), str(config))

    rows = backend.query("inventory_lookup", {"sku": "SKU-1"}, 10)

    assert rows == [{"sku": "SKU-1", "warehouse_code": "WH-A", "available_quantity": 12}]
