# Configuration

`infrastructure/conf` 负责配置加载、环境变量插值和日志初始化。

## 文件

| 文件 | 职责 |
| --- | --- |
| `config_local.yaml.example` | 本地 YAML 配置模板 |
| `settings.py` | 全局配置对象 |
| `yaml_config.py` | YAML 读取 |
| `env_interpolate.py` | 展开 `${VAR}` 环境变量占位符 |
| `logger_config.py` | 日志初始化 |

创建本地配置：

```powershell
Copy-Item infrastructure/conf/config_local.yaml.example infrastructure/conf/config_local.yaml
```

`config_local.yaml` 可能包含本地连接值，已被 git 忽略。

## MCP 环境变量

MCP 配置只从环境变量读取。不要把真实 MCP URL、API key、用户白名单或数据库连接值写进已跟踪的 YAML 或 Markdown 文件。

| 变量 | 作用 |
| --- | --- |
| `MCP_ENABLED` | MCP 总开关 |
| `BUSINESS_DB_MCP_URL` | 业务数据库 MCP 客户端地址 |
| `BUSINESS_DB_MCP_API_KEY` | 业务数据库 MCP 客户端 API key |
| `BUSINESS_DB_MCP_ALLOW_TOOLS` | 业务工具白名单，逗号分隔 |
| `BUSINESS_DB_MCP_ALLOWED_USERS` | 允许使用业务工具的飞书 open_id 白名单，逗号分隔 |
| `BUSINESS_DB_MCP_TIMEOUT_SECONDS` | 业务 MCP 客户端超时时间 |
| `BUSINESS_DB_MCP_MAX_ROWS` | 业务工具最大返回行数 |
| `BUSINESS_DB_SKILL_ENABLED` | 业务数据库运行时 Skill 开关 |
| `BUSINESS_DB_SKILL_FILE` | Markdown Skill 文件名，默认 `business_database_mcp.md` |
| `BUSINESS_DB_QUERY_GUARD_ENABLED` | 业务工具调用前 guard 开关 |
| `BUSINESS_DB_QUERY_MAX_WINDOW_DAYS` | 最大查询时间窗口，默认 30 |
| `BUSINESS_DB_QUERY_RATE_LIMIT_COUNT` | 单个窗口内单用户最大查询次数，默认 3 |
| `BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS` | 限流窗口，默认 60 |
| `BUSINESS_DB_QUERY_GUARD_REDIS_URL` | 可选 Redis URL，用于跨进程限流 |
| `BUSINESS_DB_MCP_HOST` / `BUSINESS_DB_MCP_PORT` / `BUSINESS_DB_MCP_PATH` | 业务 MCP 服务监听配置 |
| `BUSINESS_DB_BACKEND` | 业务后端：`http` 或 `sqlite` |
| `BUSINESS_DB_QUERY_API_URL` | `http` 后端的业务查询 API URL |
| `BUSINESS_DB_QUERY_API_KEY` | 业务查询 API 可选 API key |
| `BUSINESS_DB_QUERY_API_TIMEOUT_SECONDS` | 业务查询 API 超时时间 |
| `BUSINESS_DB_SQLITE_PATH` | 本地开发/演示用 SQLite 文件 |
| `BUSINESS_DB_QUERY_CONFIG_PATH` | SQLite 参数化查询模板路径 |
| `WEB_MCP_ENABLED` | 搜索/网页 MCP 开关 |
| `WEB_MCP_URL` | 搜索/网页 MCP 客户端地址 |
| `WEB_MCP_API_KEY` | 搜索/网页 MCP 客户端 API key |
| `WEB_MCP_HOST` / `WEB_MCP_PORT` / `WEB_MCP_PATH` | 搜索/网页 MCP 服务监听配置 |
| `WEB_MCP_ALLOW_TOOLS` | 网页工具白名单，逗号分隔 |
| `WEB_MCP_TIMEOUT_SECONDS` | 网页 MCP 超时时间 |
| `WEB_MCP_MAX_RESULTS` | 最大网页搜索结果数 |
| `WEB_MCP_FETCH_MAX_CHARS` | 最大网页正文读取长度 |
| `TAVILY_API_URL` / `TAVILY_API_KEY` | Tavily 兼容搜索 endpoint 和 key |
