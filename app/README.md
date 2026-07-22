# App

`app/` contains the online application layer. It receives user requests, runs the agent assistant, calls tools, and formats replies for channels or HTTP clients.

## Modules

| Module | Responsibility | Entry Point |
| --- | --- | --- |
| [`assistant/`](assistant/README.md) | Agent orchestration, runtime skills, tool calls, memory, prompts, and answer formatting | `app.assistant.factory.build_agent_service` |
| [`channels/`](channels/README.md) | Channel protocol adapters and Lark/Feishu interaction | `python -m app.channels.lark.bot` |
| [`api/`](api/README.md) | Optional recall, embedding, and conversion HTTP APIs | `uvicorn app.api.main:app --port <port>` |

## Boundaries

- `channels` handles platform events, identity, messages, and files.
- `assistant` decides whether to answer directly, retrieve knowledge, call MCP tools, or use runtime skills.
- `api` exposes standalone capabilities for other systems; it is not required for the Lark bot path.
- Model clients, storage clients, MCP clients, and configuration are provided by `infrastructure`.

