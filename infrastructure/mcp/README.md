# MCP

This directory contains the MCP clients, auth helpers, configuration helpers, backend adapters, and server entry points used by Lark Agent.

The project intentionally keeps the external MCP surface small:

| Service | Tools |
| --- | --- |
| Business database MCP | `inventory_lookup`, `inventory_batch_lookup`, `order_status`, `product_lookup` |
| Search/web MCP | `web_search`, `web_fetch` |

## Start Services

```powershell
python -m infrastructure.mcp.servers.business_db
python -m infrastructure.mcp.servers.web_search
```

Both services provide:

- `GET /health`: health check and exposed tool list.
- MCP Streamable HTTP endpoint at the path configured by environment variables.
- Optional API-key auth through `Authorization: Bearer <key>` or `X-API-Key`.

## Business Database MCP

The assistant does not submit SQL. It calls fixed business operations with structured arguments:

- `inventory_lookup`: current inventory for one SKU.
- `inventory_batch_lookup`: current inventory for several SKUs.
- `order_status`: current state and milestones for one order.
- `product_lookup`: product lookup by name, SKU, keyword, or category.

Supported backends:

1. `BUSINESS_DB_BACKEND=http`: recommended for a real business database service. MCP posts `operation`, `arguments`, and `max_rows` to `BUSINESS_DB_QUERY_API_URL`; your database project executes the prepared query and returns `{"rows": [...]}`.
2. `BUSINESS_DB_BACKEND=sqlite`: local development/demo mode. It uses `BUSINESS_DB_SQLITE_PATH` and a private query config file. SQLite is opened in read-only mode and query templates accept only a single `SELECT` or CTE statement.

When your SQL Server side is ready, implement the four operation names in your database project and point `BUSINESS_DB_QUERY_API_URL` to it. The Lark Agent does not need table schema or SQL in its prompt.

## Business Tool Guards

Agent-side guards run before business database MCP calls:

- Private chat and user allowlist are checked before tools are exposed.
- Group mentions never expose business database MCP tools.
- Structured parameters are checked before forwarding to MCP.
- Query date windows are limited to `BUSINESS_DB_QUERY_MAX_WINDOW_DAYS`, default 30.
- Each user is limited by `BUSINESS_DB_QUERY_RATE_LIMIT_COUNT` per `BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS`, default 3 calls per 60 seconds.
- `BUSINESS_DB_QUERY_GUARD_REDIS_URL` enables Redis-backed rate limiting; otherwise the process uses an in-memory fallback.

The Markdown runtime skill in `app/assistant/skills/business_database_mcp.md` guides clarification before tool use, but these code guards remain the final enforcement layer.

## Search/Web MCP

`web_search` uses Tavily-compatible environment variables. `web_fetch` reads public webpage text and rejects:

- Local or private network addresses.
- Credential-bearing URLs.
- Non-text responses.
- Oversized responses beyond configured limits.

## Agent Switches

Set `MCP_ENABLED=true` to register business database tools. Set `WEB_MCP_ENABLED=true` as well to expose `web_search` and `web_fetch` to the agent.

Tool allowlists are controlled by:

- `BUSINESS_DB_MCP_ALLOW_TOOLS`
- `WEB_MCP_ALLOW_TOOLS`

Runtime endpoints, API keys, host, port, path, backend connection, and limits are documented in [infrastructure/conf/README.md](../conf/README.md).

