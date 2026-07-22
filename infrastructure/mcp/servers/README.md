# MCP Servers

This directory contains runnable Streamable HTTP MCP services.

| Module | Responsibility |
| --- | --- |
| `business_db.py` | Publishes inventory, order status, and product lookup tools |
| `web_search.py` | Publishes public web search and webpage reading tools |

## Start

```powershell
python -m infrastructure.mcp.servers.business_db
python -m infrastructure.mcp.servers.web_search
```

Server host, port, path, auth, backend connection, and tool allowlists are all read from environment variables.

## Boundary

These services are independent from the current Lark Agent runtime. Lark Agent consumes them through `app/assistant/agent/tools/mcp_tools.py`, and other agents or projects can connect with their own MCP clients.

Business database connection settings and query templates must stay outside this directory unless they are local examples without real values.

