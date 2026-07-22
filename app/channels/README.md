# Channels

`app/channels` 保存外部渠道适配。渠道代码只处理平台协议、身份、消息、文件和回复，不实现 Agent 决策或检索逻辑。

## 当前渠道

| 渠道 | 作用 |
| --- | --- |
| [`lark/`](lark/README.md) | 飞书长连接 bot、消息回复、反馈入口和群文件下载 |

新增渠道时，应通过 `app.assistant.factory` 创建助手，并把 user id、chat id、chat type 等运行时身份传给 `AgentService.answer()`。
