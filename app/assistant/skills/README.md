# Assistant Skills

本目录保存 Lark Agent 的 Markdown 运行时 Skill。

Skill 用来描述某类工具工作流：什么时候适用、哪些字段必须追问、哪些值不能猜、工具返回后应该如何回答。

这些文件可以提交到仓库。它们只应包含工作流规则、示例和回答规范。运行时地址、API key、用户白名单、数据库凭据和 MCP endpoint 都应放在环境变量中。

## 当前 Skill

| Skill | 作用 |
| --- | --- |
| [`business_database_mcp.md`](business_database_mcp.md) | 指导库存、订单、商品查询等业务数据库 MCP 调用流程。 |

## 运行时激活

`business_database.py` 负责轻量关键词和标识符检测。当授权私聊请求像是库存、订单或商品查询时，loader 会把 `business_database_mcp.md` 渲染为临时 system message，注入当前 Agent run。

渲染后的 Skill 不会写入对话记忆。本轮回答结束后，后续轮次只有再次命中激活规则才会重新获得该 Skill。

## 职责划分

Markdown Skill 指导 Agent：

- 缺 SKU、订单号、商品关键词、仓库或日期范围时先追问。
- 避免猜测业务标识符。
- 优先使用精确标识符，而不是宽泛描述。
- 只根据业务数据库返回的 rows 作答。

代码继续执行最终边界：

- 业务数据库工具仅限飞书私聊。
- 用户白名单从环境变量读取。
- 单次查询时间窗口默认最多 30 天。
- 单用户默认 60 秒最多 3 次业务查询。
- Agent 只发送结构化 MCP 参数，不发送 SQL。
