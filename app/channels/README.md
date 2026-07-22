# Channels

`app/channels` contains external channel adapters. Channel code handles platform protocol, identity, messages, files, and replies. It does not implement agent decisions or retrieval logic.

## Current Channel

| Channel | Purpose |
| --- | --- |
| [`lark/`](lark/README.md) | Lark/Feishu long-connection bot, message replies, feedback entry, and group file download |

New channels should create the assistant through `app.assistant.factory` and pass runtime identity such as user id, chat id, and chat type into `AgentService.answer()`.

