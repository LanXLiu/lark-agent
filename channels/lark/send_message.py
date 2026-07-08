from __future__ import annotations

import argparse
import json

from channels.lark.lark_config import load_settings
from channels.lark.lark_api import get_tenant_access_token, send_text_message_to_chat


def main() -> None:
    parser = argparse.ArgumentParser(description="以飞书应用机器人身份向群聊发送文本消息")
    parser.add_argument("--chat-id", help="群聊 chat_id，例如 oc_xxx；不传时读取 LARK_DEFAULT_CHAT_ID")
    parser.add_argument("--text", required=True, help="要发送的文本内容")
    args = parser.parse_args()

    settings = load_settings(require_enterprise_server=False)
    chat_id = args.chat_id or settings.lark_default_chat_id
    if not chat_id:
        parser.error("请通过 --chat-id 指定群聊 chat_id，或在 .env 中配置 LARK_DEFAULT_CHAT_ID")

    tenant_access_token = get_tenant_access_token(
        settings.lark_open_api_base_url,
        settings.lark_app_id,
        settings.lark_app_secret,
    )
    response = send_text_message_to_chat(
        settings.lark_open_api_base_url,
        tenant_access_token,
        chat_id,
        args.text,
    )

    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
