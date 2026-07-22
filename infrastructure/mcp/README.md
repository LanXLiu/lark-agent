# MCP

本目录包含 Lark Agent 使用的 MCP 客户端、鉴权、配置工具、后端适配和服务入口。

项目刻意保持外部 MCP 面较小：

| 服务 | 工具 |
| --- | --- |
| 业务数据库 MCP | `inventory_lookup`、`inventory_batch_lookup`、`order_status`、`product_lookup` |
| 搜索/网页 MCP | `web_search`、`web_fetch` |

## 启动服务

```powershell
python -m infrastructure.mcp.servers.business_db
python -m infrastructure.mcp.servers.web_search
```

两个服务都提供：

- `GET /health`：健康检查和已暴露工具列表。
- MCP Streamable HTTP endpoint：路径由环境变量配置。
- 可选 API key 鉴权：支持 `Authorization: Bearer <key>` 或 `X-API-Key`。

## 业务数据库 MCP

Agent 不提交 SQL，只用结构化参数调用固定业务操作：

- `inventory_lookup`：查询单个 SKU 当前库存。
- `inventory_batch_lookup`：批量查询多个 SKU 当前库存。
- `order_status`：查询单个订单状态和节点。
- `product_lookup`：按名称、SKU、关键词或分类查商品。

支持两种后端：

1. `BUSINESS_DB_BACKEND=http`：推荐用于真实业务数据库服务。MCP 将 `operation`、`arguments`、`max_rows` POST 到 `BUSINESS_DB_QUERY_API_URL`，由你的数据库项目执行封装好的查询并返回 `{"rows": [...]}`。
2. `BUSINESS_DB_BACKEND=sqlite`：本地开发/演示模式。使用 `BUSINESS_DB_SQLITE_PATH` 和私有查询配置文件。SQLite 以只读模式打开，查询模板只接受单条 `SELECT` 或 CTE。

等 SQL Server 侧准备好后，只需要在数据库项目中实现这四个 operation，并把 `BUSINESS_DB_QUERY_API_URL` 指向它。Lark Agent 不需要知道表结构，也不需要在 prompt 中写 SQL。

## 业务工具 Guard

业务数据库 MCP 调用前会执行 Agent 侧 guard：

- 工具暴露前检查私聊和用户白名单。
- 群聊 @ 场景不暴露业务数据库工具。
- 转发到 MCP 前检查结构化参数。
- 查询日期窗口由 `BUSINESS_DB_QUERY_MAX_WINDOW_DAYS` 控制，默认 30 天。
- 单用户调用频率由 `BUSINESS_DB_QUERY_RATE_LIMIT_COUNT` 和 `BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS` 控制，默认 60 秒 3 次。
- 配置 `BUSINESS_DB_QUERY_GUARD_REDIS_URL` 后使用 Redis 做跨进程限流；未配置时使用进程内兜底。

`app/assistant/skills/business_database_mcp.md` 中的 Markdown Skill 负责指导调用前澄清，但这些代码 guard 仍是最终执行层。

## 搜索/网页 MCP

`web_search` 使用 Tavily 兼容环境变量。`web_fetch` 读取公开网页正文，并拒绝：

- 本地或内网地址。
- 带凭据的 URL。
- 非文本响应。
- 超出配置大小的响应。

## Agent 开关

设置 `MCP_ENABLED=true` 后注册业务数据库工具。再设置 `WEB_MCP_ENABLED=true` 后，Agent 可以看到 `web_search` 和 `web_fetch`。

工具白名单由以下变量控制：

- `BUSINESS_DB_MCP_ALLOW_TOOLS`
- `WEB_MCP_ALLOW_TOOLS`

运行时 endpoint、API key、host、port、path、后端连接和限制项见 [infrastructure/conf/README.md](../conf/README.md)。
