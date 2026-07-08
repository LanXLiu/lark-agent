from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

LOGGER = logging.getLogger(__name__)


def build_relay_payload(event: dict[str, Any]) -> dict[str, Any]:
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}

    content = parse_message_content(message.get("content"))
    chat_type = event.get("chat_type") or message.get("chat_type")

    return {
        "event_type": "im.message.receive_v1",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "chat_type": chat_type,
        "message": {
            "message_id": message.get("message_id"),
            "chat_id": message.get("chat_id"),
            "chat_type": message.get("chat_type") or chat_type,
            "message_type": message.get("message_type"),
            "create_time": message.get("create_time"),
            "content": content,
            "raw_content": message.get("content"),
        },
        "sender": {
            "open_id": sender_id.get("open_id") or sender.get("open_id"),
            "user_id": sender_id.get("user_id") or sender.get("user_id"),
            "union_id": sender_id.get("union_id") or sender.get("union_id"),
            "sender_type": sender.get("sender_type"),
            "tenant_key": sender.get("tenant_key"),
        },
        "raw_event": event,
    }


def parse_message_content(content: Any) -> Any:
    if content is None:
        return None
    if not isinstance(content, str):
        return content

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"text": content}


def post_to_enterprise_server(
    url: str,
    payload: dict[str, Any],
    *,
    token: str | None = None,
    timeout_seconds: float = 2.5,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = response.getcode()
            if status < 200 or status >= 300:
                raise RuntimeError(f"企业服务器返回非 2xx 状态码：{status}")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"企业服务器返回错误：{exc.code} {exc.reason}，响应体：{response_body}"
        ) from exc
