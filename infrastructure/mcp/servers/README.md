# MCP Servers

本目录包含可独立运行的 Streamable HTTP MCP 服务。

| 模块 | 职责 |
| --- | --- |
| `business_db.py` | 发布库存、订单状态和商品查询工具 |
| `web_search.py` | 发布公开网页搜索和网页正文读取工具 |

## 启动

```powershell
python -m infrastructure.mcp.servers.business_db
python -m infrastructure.mcp.servers.web_search
```

服务 host、port、path、鉴权、后端连接和工具白名单全部从环境变量读取。

## 边界

这些服务独立于当前 Lark Agent 运行时。Lark Agent 通过 `app/assistant/agent/tools/mcp_tools.py` 消费它们，其他 Agent 或项目也可以用自己的 MCP 客户端连接。

业务数据库连接配置和查询模板不应保存在本目录，除非只是没有真实值的本地示例。
