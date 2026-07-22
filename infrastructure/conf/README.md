# Configuration

`infrastructure/conf` contains configuration loading, environment interpolation, and logging setup.

## Files

| File | Responsibility |
| --- | --- |
| `config_local.yaml.example` | Local YAML configuration template |
| `settings.py` | Global settings object |
| `yaml_config.py` | YAML reader |
| `env_interpolate.py` | Expands `${VAR}` placeholders from environment variables |
| `logger_config.py` | Logging initialization |

Create local configuration:

```powershell
Copy-Item infrastructure/conf/config_local.yaml.example infrastructure/conf/config_local.yaml
```

`config_local.yaml` may contain local connection values and is ignored by git.

## MCP Environment Variables

MCP configuration is environment-only. Do not write real MCP URLs, API keys, user allowlists, or database connection values into tracked YAML or Markdown files.

| Variable | Purpose |
| --- | --- |
| `MCP_ENABLED` | Global MCP switch |
| `BUSINESS_DB_MCP_URL` | Business database MCP client URL |
| `BUSINESS_DB_MCP_API_KEY` | Business database MCP client API key |
| `BUSINESS_DB_MCP_ALLOW_TOOLS` | Comma-separated business tool allowlist |
| `BUSINESS_DB_MCP_ALLOWED_USERS` | Comma-separated Lark open_id allowlist for private-chat business tools |
| `BUSINESS_DB_MCP_TIMEOUT_SECONDS` | Business MCP client timeout |
| `BUSINESS_DB_MCP_MAX_ROWS` | Maximum rows returned by business tools |
| `BUSINESS_DB_SKILL_ENABLED` | Runtime business database skill switch |
| `BUSINESS_DB_SKILL_FILE` | Markdown skill filename, default `business_database_mcp.md` |
| `BUSINESS_DB_QUERY_GUARD_ENABLED` | Business pre-call guard switch |
| `BUSINESS_DB_QUERY_MAX_WINDOW_DAYS` | Maximum query date window, default 30 |
| `BUSINESS_DB_QUERY_RATE_LIMIT_COUNT` | Per-user query limit in one window, default 3 |
| `BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit window, default 60 |
| `BUSINESS_DB_QUERY_GUARD_REDIS_URL` | Optional Redis URL for cross-process rate limiting |
| `BUSINESS_DB_MCP_HOST` / `BUSINESS_DB_MCP_PORT` / `BUSINESS_DB_MCP_PATH` | Business MCP server listening config |
| `BUSINESS_DB_BACKEND` | Business backend: `http` or `sqlite` |
| `BUSINESS_DB_QUERY_API_URL` | Existing business query API URL for the `http` backend |
| `BUSINESS_DB_QUERY_API_KEY` | Optional API key for the business query API |
| `BUSINESS_DB_QUERY_API_TIMEOUT_SECONDS` | Timeout for the business query API |
| `BUSINESS_DB_SQLITE_PATH` | Local SQLite file for development/demo |
| `BUSINESS_DB_QUERY_CONFIG_PATH` | Private parameterized query template path for SQLite |
| `WEB_MCP_ENABLED` | Search/web MCP switch |
| `WEB_MCP_URL` | Search/web MCP client URL |
| `WEB_MCP_API_KEY` | Search/web MCP client API key |
| `WEB_MCP_HOST` / `WEB_MCP_PORT` / `WEB_MCP_PATH` | Search/web MCP server listening config |
| `WEB_MCP_ALLOW_TOOLS` | Comma-separated web tool allowlist |
| `WEB_MCP_TIMEOUT_SECONDS` | Web MCP client/server timeout |
| `WEB_MCP_MAX_RESULTS` | Maximum web search results |
| `WEB_MCP_FETCH_MAX_CHARS` | Maximum fetched webpage text length |
| `TAVILY_API_URL` / `TAVILY_API_KEY` | Tavily-compatible search endpoint and key |

