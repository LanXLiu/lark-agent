# Assistant Skills

This directory stores Markdown runtime skills used by Lark Agent.

Skills describe workflow behavior for a tool family: when it applies, which fields must be clarified, which values must not be guessed, and how the assistant should answer after a tool returns data.

The files here are safe to commit. They should contain workflow rules, examples, and answer policy only. Runtime addresses, API keys, user allowlists, database credentials, and MCP endpoints stay in environment variables.

## Current Skills

| Skill | Purpose |
| --- | --- |
| [`business_database_mcp.md`](business_database_mcp.md) | Guides business database MCP calls for inventory, order, and product lookup workflows. |

## Runtime Activation

`business_database.py` performs lightweight keyword and identifier detection. When an authorized private-chat request looks like inventory, order, or product lookup, the loader renders `business_database_mcp.md` into a temporary system message for that one agent run.

The rendered skill is not stored in conversation memory. After the current answer finishes, later turns only receive the skill again if they independently match the activation rules.

## Division Of Responsibility

The Markdown skill guides the assistant:

- Ask for missing SKU, order number, product keyword, warehouse, or date range.
- Avoid guessing business identifiers.
- Prefer exact identifiers over broad text.
- Answer only from returned business rows.

Code still enforces final boundaries:

- Lark private chat only for business database tools.
- User allowlist from environment variables.
- Maximum query window, currently 30 days by default.
- Per-user rate limit, currently 3 calls per 60 seconds by default.
- Structured MCP arguments only; the agent does not send SQL.

