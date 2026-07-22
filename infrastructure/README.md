# Infrastructure

`infrastructure/` 提供配置、模型客户端、存储和 MCP 连接等基础设施适配。上层模块依赖这些公开接口，不直接维护凭据、协议或连接细节。

## 模块

| 模块 | 职责 |
| --- | --- |
| [`conf/`](conf/README.md) | 环境变量、YAML 加载、变量插值和日志配置 |
| [`db/`](db/README.md) | MinIO 和 Qdrant 客户端 |
| [`model/`](model/README.md) | LLM、embedding、rerank 和 OCR 客户端 |
| [`mcp/`](mcp/README.md) | 业务数据库 MCP、搜索/网页 MCP、客户端、鉴权和配置工具 |
| `object_storage.py` | 对象存储公共接口 |
| `vector_store.py` | 向量存储公共接口 |

## 原则

- 真实凭据和 endpoint 来自环境变量或被忽略的本地文件。
- MCP 服务 host、port、path、鉴权、后端连接和白名单全部由环境变量驱动。
- 业务代码调用 infrastructure 接口，不重复维护连接逻辑。
- MCP 服务独立运行，方便其他 Agent 或项目复用。
