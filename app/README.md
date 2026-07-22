# App

`app/` 是在线应用层，负责接收用户请求、运行 Agent 助手、调用工具，并把结果格式化后返回给飞书或 HTTP 调用方。

## 模块

| 模块 | 职责 | 入口 |
| --- | --- | --- |
| [`assistant/`](assistant/README.md) | Agent 编排、运行时 Skill、工具调用、记忆、提示词和答案格式化 | `app.assistant.factory.build_agent_service` |
| [`channels/`](channels/README.md) | 渠道协议适配和飞书交互 | `python -m app.channels.lark.bot` |
| [`api/`](api/README.md) | 可选的召回、向量化、文档转换 HTTP API | `uvicorn app.api.main:app --port <port>` |

## 边界

- `channels` 处理平台事件、身份、消息和文件。
- `assistant` 决定是否直接回答、检索知识库、调用 MCP 工具或注入运行时 Skill。
- `api` 为其他系统暴露独立能力，不是飞书 bot 主链路的必经路径。
- 模型客户端、存储客户端、MCP 客户端和配置由 `infrastructure` 提供。
