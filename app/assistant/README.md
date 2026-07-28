# Assistant Runtime

`app/assistant` 是 Lark Agent 的运行时模块，连接渠道、对话记忆、运行时 Skill、工具和答案格式化。主编排逻辑位于 `agent/graph.py`，使用 LangGraph 和 Function Calling 实现。

## 文件

| 路径 | 职责 |
| --- | --- |
| `factory.py` | 运行时装配入口，创建 LLM 客户端、检索器和 `AgentService`。 |
| `agent/graph.py` | Agent 循环：携带 tools 调 LLM、执行工具、组装最终答案、联网降级、工具轮次限制和流式事件回调。 |
| `agent/tools/` | 工具抽象、注册表、知识库检索、时间工具、MCP 代理、网页搜索和业务查询 guard。 |
| `skills/` | Markdown 运行时 Skill 和激活逻辑；当前 Skill 用于指导业务数据库 MCP 调用。 |
| `qa_service.py` | 统一回答结构、来源格式化和拒答辅助逻辑。 |
| `memory.py` | 对话记忆窗口、摘要和上下文构建。 |
| `memory_store.py` | 可选 SQLite 对话记忆持久化。 |
| `llm_client.py` | 支持工具调用、重试和 SSE 文本流式输出的聊天客户端。 |
| `prompts/` | 系统提示词和 prompt 构建函数。 |

## Agent 流程

```text
问题
  -> 构建 ToolContext
  -> 命中规则时为本轮附加运行时 Skill
  -> LLM 判断是否调用工具
  -> 执行被选中的工具
  -> 进入最终作答阶段
  -> 组装答案和来源
```

本项目不在每个问题前跑一个大型固定意图分类器。主要路由由 Function Calling 完成，代码侧负责控制工具可见性和硬约束。

当渠道传入 `event_callback` 时，Agent 会把“理解问题、调用工具、检索完成、开始生成”等状态发回渠道；最终作答阶段使用 LLM SSE，把答案增量交给渠道侧展示。未传回调时仍走原同步接口。

## 运行时 Skill

运行时 Skill 是 `skills/` 下的 Markdown 文件，属于产品行为说明，不保存任何真实配置。

`skills/business_database_mcp.md` 描述调用业务数据库 MCP 前应该如何准备：

- 哪些问题属于库存、订单或商品查询。
- 哪些字段必须在调用工具前问清楚。
- 哪些标识符不能由模型猜测。
- MCP 返回 rows 后如何组织回答。
- 空结果或歧义结果如何处理。

`skills/business_database.py` 决定当前轮是否注入该 Skill，检查项包括：

- 库存、现货、订单、发货、商品、产品、SKU 等中英文关键词。
- 类 SKU 或订单号的标识符。
- 飞书私聊上下文。
- 环境变量中的用户白名单。

Skill 会作为临时 system message 插入当前 Agent run，不写入对话记忆。后续轮次只有再次命中激活规则才会重新注入。

## 业务数据库工具边界

业务数据库 MCP 工具只在授权私聊请求中可见。Agent 向固定 MCP 工具传结构化参数，不生成 SQL。

调用业务数据库 MCP 前，`agent/tools/business_guards.py` 会检查：

- 查询时间窗口，默认 30 天。
- 单用户调用频率，默认 60 秒 3 次。
- 可选 Redis 跨进程限流。
- 日期范围合法性。

即使 Markdown Skill 已要求 Agent 先澄清，最终限制仍由代码执行。

## 对话记忆

对话记忆分为两个视图：

- 改写上下文：短历史，用于处理“这个”“刚才那个”等指代。
- 回答上下文：摘要加最近轮次，用于保持多轮回答连贯。

运行时 Skill 不进入 memory，避免长期 prompt 偏移。
