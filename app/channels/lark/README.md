# app/channels/lark — 飞书接入通道

飞书机器人通道：接收群消息、触发 agent 助手回答、回复带来源和反馈按钮的答案，以及下载群文档入库。通过 lark-oapi 长连接（websocket）与飞书通信，无需公网入站。

## 文件

| 文件 | 职责 |
|---|---|
| `bot.py` | **入口**。长连接客户端；收消息 → 去重 → 快速 ack → 入**有界队列**（削峰）→ 固定 worker 线程用单例 agent助手服务跑问答；卡片按钮回调（反馈）。队列满时返回稍后重试。`python -m app.channels.lark.bot` 启动。 |
| `lark_api.py` | 飞书 OpenAPI 封装：tenant_access_token、发消息、贴表情、取云文档原生 markdown、群名/文档名查询。 |
| `download.py` | 下载群文档/附件到 MinIO。`python -m app.channels.lark.download` 可单独运行。 |
| `lark_markdown.py` | 飞书原生 markdown 清洗（反转义、HTML 表格转 md）。 |
| `feedback.py` | 👍/👎 反馈卡片构造与落盘（群聊多人各记一份）。 |
| `source_names.py` | 飞书 ID → 群名/文档名解析（带缓存）。 |
| `observability.py` | 问答结构化日志 `QaTrace`。 |
| `lark_config.py` | 从 `.env` 读飞书凭证与运行参数（`Settings`）。 |
| `minio_uploader.py` / `relay.py` / `send_message.py` | MinIO 上传 / 消息转发 / 主动发消息工具。 |

## 说明

问答不在本模块实现。`bot.py` 通过 `app.assistant.factory` 创建 agent助手服务，本模块只负责飞书侧的收发与文件获取。

**并发兜底**：问答耗时数秒，websocket 回调必须秒 ack（否则飞书重投）。`bot.py` 收消息后立即入有界队列（`RAG_QUEUE_MAXSIZE`），由固定数量 worker（`RAG_WORKER_COUNT`）消费——worker 数即「最多几路并发打百炼」。队列满时对提问优雅回「稍后再试」，而非无限堆积撑爆内存。所有 worker 共用一个启动时建好的单例 Agent 服务（其 `answer` 无共享可变状态，跨线程安全）。
