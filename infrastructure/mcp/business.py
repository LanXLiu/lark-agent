"""Business query definitions and backends for the business database MCP."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Protocol

import httpx

from infrastructure.mcp.config import required_env_float, required_env_int

BUSINESS_TOOLS: dict[str, dict[str, Any]] = {
    "inventory_lookup": {
        "description": "Query current inventory for one SKU, optionally in one warehouse.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sku": {"type": "string", "description": "Exact SKU code"},
                "warehouse_code": {"type": "string", "description": "Optional warehouse code"},
            },
            "required": ["sku"],
            "additionalProperties": False,
        },
    },
    "inventory_batch_lookup": {
        "description": "Query current inventory for several SKU codes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "skus": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "warehouse_code": {"type": "string", "description": "Optional warehouse code"},
            },
            "required": ["skus"],
            "additionalProperties": False,
        },
    },
    "order_status": {
        "description": "Query the current state and milestones of an order.",
        "inputSchema": {
            "type": "object",
            "properties": {"order_no": {"type": "string", "description": "Exact order number"}},
            "required": ["order_no"],
            "additionalProperties": False,
        },
    },
    "product_lookup": {
        "description": "Find products by name, SKU, or keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Product name, SKU, or keyword"},
                "category": {"type": "string", "description": "Optional category filter"},
            },
            "required": ["keyword"],
            "additionalProperties": False,
        },
    },
}


class BusinessBackend(Protocol):
    def query(self, operation: str, arguments: dict[str, Any], max_rows: int) -> list[dict[str, Any]]: ...


class UnconfiguredBackend:
    def query(self, operation: str, arguments: dict[str, Any], max_rows: int) -> list[dict[str, Any]]:
        raise RuntimeError(
            "Business database backend is not configured. Set BUSINESS_DB_BACKEND and its connection settings."
        )


class HttpBusinessBackend:
    """Calls a business query API using operation names and typed arguments."""

    def __init__(self, url: str, api_key: str, timeout_seconds: float) -> None:
        self.url = url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def query(self, operation: str, arguments: dict[str, Any], max_rows: int) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        response = httpx.post(
            self.url,
            json={"operation": operation, "arguments": arguments, "max_rows": max_rows},
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        rows = data.get("rows", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise RuntimeError("Business query API must return a row list or {'rows': [...]} object")
        return [dict(row) for row in rows[:max_rows] if isinstance(row, dict)]


class SqliteBusinessBackend:
    """Runs administrator-defined, parameterized SELECT templates against SQLite."""

    def __init__(self, db_path: str, query_config_path: str) -> None:
        self.db_path = str(Path(db_path).resolve())
        with open(query_config_path, encoding="utf-8") as fp:
            config = json.load(fp)
        queries = config.get("queries", config)
        if not isinstance(queries, dict):
            raise ValueError("Business query config must contain a 'queries' object")
        self.queries = {str(name): str(sql).strip() for name, sql in queries.items()}
        for sql in self.queries.values():
            if not sql.lower().startswith(("select ", "with ")) or ";" in sql.rstrip(";"):
                raise ValueError("Business query templates must contain one SELECT/CTE statement")

    def query(self, operation: str, arguments: dict[str, Any], max_rows: int) -> list[dict[str, Any]]:
        sql = self.queries.get(operation)
        if not sql:
            raise RuntimeError(f"No SQL template configured for operation: {operation}")
        params = dict(arguments)
        params.setdefault("warehouse_code", None)
        params.setdefault("category", None)
        if operation == "inventory_batch_lookup":
            skus = [str(item) for item in arguments.get("skus") or []][:50]
            if not skus:
                return []
            placeholders = ", ".join(f":sku_{index}" for index in range(len(skus)))
            sql = sql.replace("{{skus}}", placeholders)
            params.update({f"sku_{index}": sku for index, sku in enumerate(skus)})
        uri = Path(self.db_path).as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5.0) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(sql, params)
            return [dict(row) for row in cursor.fetchmany(max_rows)]


def build_business_backend() -> BusinessBackend:
    backend = os.getenv("BUSINESS_DB_BACKEND", "").strip().lower()
    if backend == "http":
        url = os.getenv("BUSINESS_DB_QUERY_API_URL", "").strip()
        if not url:
            return UnconfiguredBackend()
        return HttpBusinessBackend(
            url,
            os.getenv("BUSINESS_DB_QUERY_API_KEY", "").strip(),
            required_env_float("BUSINESS_DB_QUERY_API_TIMEOUT_SECONDS"),
        )
    if backend == "sqlite":
        db_path = os.getenv("BUSINESS_DB_SQLITE_PATH", "").strip()
        config_path = os.getenv("BUSINESS_DB_QUERY_CONFIG_PATH", "").strip()
        if db_path and config_path:
            return SqliteBusinessBackend(db_path, config_path)
    return UnconfiguredBackend()


def execute_business_query(
    backend: BusinessBackend,
    operation: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    max_rows = required_env_int("BUSINESS_DB_MCP_MAX_ROWS", maximum=200)
    rows = backend.query(operation, arguments, max_rows)
    return {"operation": operation, "row_count": len(rows), "rows": rows}
