from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class LarkApiError(RuntimeError):
    pass


def get_tenant_access_token(
    base_url: str,
    app_id: str,
    app_secret: str,
    *,
    timeout_seconds: float = 5,
) -> str:
    response = post_json(
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
        timeout_seconds=timeout_seconds,
    )

    if response.get("code") != 0:
        raise LarkApiError(f"get tenant_access_token failed: {response}")

    token = response.get("tenant_access_token")
    if not token:
        raise LarkApiError(f"missing tenant_access_token in response: {response}")
    return token


def add_message_reaction(
    base_url: str,
    tenant_access_token: str,
    message_id: str,
    emoji_type: str = "OK",
    *,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """给指定消息贴一个表情回应（reaction），用于快速反馈「已收到」。

    不产生新消息，直接贴在用户原消息上。emoji_type 见飞书表情枚举，
    常用：OK / THUMBSUP / DONE。
    """
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    response = post_json(
        f"{base_url}/open-apis/im/v1/messages/{encoded_message_id}/reactions",
        {"reaction_type": {"emoji_type": emoji_type}},
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )
    if response.get("code") != 0:
        raise LarkApiError(f"add message reaction failed: {response}")
    return response


def reply_card_to_message(
    base_url: str,
    tenant_access_token: str,
    message_id: str,
    card: dict[str, Any],
    *,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """以「引用回复」的形式回应指定消息，内容为 interactive 交互卡片。

    用于发送带按钮（如 👍/👎 反馈）的答案，挂在原提问下面。
    """
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    response = post_json(
        f"{base_url}/open-apis/im/v1/messages/{encoded_message_id}/reply",
        {
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )
    if response.get("code") != 0:
        raise LarkApiError(f"reply card failed: {response}")
    return response


def reply_text_to_message(
    base_url: str,
    tenant_access_token: str,
    message_id: str,
    text: str,
    *,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """以「引用回复」的形式回应指定消息，答案会挂在原提问下面。"""
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    response = post_json(
        f"{base_url}/open-apis/im/v1/messages/{encoded_message_id}/reply",
        {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )
    if response.get("code") != 0:
        raise LarkApiError(f"reply message failed: {response}")
    return response


def send_text_message_to_chat(
    base_url: str,
    tenant_access_token: str,
    chat_id: str,
    text: str,
    *,
    timeout_seconds: float = 5,
    reply_to_message_id: str | None = None,
) -> dict[str, Any]:
    # 提供了原消息 id 时，用「引用回复」让答案挂在提问下面；否则发普通群消息
    if reply_to_message_id:
        return reply_text_to_message(
            base_url,
            tenant_access_token,
            reply_to_message_id,
            text,
            timeout_seconds=timeout_seconds,
        )
    return send_message(
        base_url,
        tenant_access_token,
        receive_id_type="chat_id",
        receive_id=chat_id,
        msg_type="text",
        content={"text": text},
        timeout_seconds=timeout_seconds,
    )


def get_bot_open_id(
    base_url: str,
    tenant_access_token: str,
    *,
    timeout_seconds: float = 5,
) -> str | None:
    response = get_json(
        f"{base_url}/open-apis/bot/v3/info",
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )
    ensure_lark_success(response, "get bot info failed")

    data = response.get("data") or {}
    bot = data.get("bot") or {}
    return data.get("open_id") or bot.get("open_id")


def list_chat_messages(
    base_url: str,
    tenant_access_token: str,
    chat_id: str,
    *,
    start_time: int | None = None,
    end_time: int | None = None,
    page_size: int = 50,
    page_limit: int | None = None,
    timeout_seconds: float = 10,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    page_token: str | None = None
    pages_read = 0

    while page_limit is None or pages_read < page_limit:
        params: dict[str, Any] = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "sort_type": "ByCreateTimeDesc",
            "page_size": page_size,
        }
        if start_time is not None:
            params["start_time"] = str(start_time)
        if end_time is not None:
            params["end_time"] = str(end_time)
        if page_token:
            params["page_token"] = page_token

        response = get_json(
            f"{base_url}/open-apis/im/v1/messages",
            headers={"Authorization": f"Bearer {tenant_access_token}"},
            params=params,
            timeout_seconds=timeout_seconds,
        )
        ensure_lark_success(response, "list chat messages failed")

        data = response.get("data") or {}
        messages.extend(data.get("items") or [])
        pages_read += 1
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break

    return messages


def get_doc_markdown(
    base_url: str,
    tenant_access_token: str,
    doc_token: str,
    *,
    doc_type: str = "docx",
    timeout_seconds: float = 30,
) -> str:
    """获取飞书新版文档(docx)的 markdown 内容。

    用 GET /open-apis/docs/v1/content?content_type=markdown 直接拿飞书原生 markdown，
    比「导出 docx 再第三方转 markdown」结构保真（标题、表格不丢失）。
    需应用权限 docs:document.content:read。仅支持 docx 类型。
    """
    response = get_json(
        f"{base_url}/open-apis/docs/v1/content",
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        params={
            "doc_token": doc_token,
            "doc_type": doc_type,
            "content_type": "markdown",
            "lang": "zh",
        },
        timeout_seconds=timeout_seconds,
    )
    ensure_lark_success(response, "get doc markdown failed")
    return str((response.get("data") or {}).get("content") or "")


def download_message_resource(
    base_url: str,
    tenant_access_token: str,
    message_id: str,
    file_key: str,
    resource_type: str,
    destination: Path,
    *,
    timeout_seconds: float = 30,
) -> None:
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    encoded_file_key = urllib.parse.quote(file_key, safe="")
    download_binary(
        f"{base_url}/open-apis/im/v1/messages/{encoded_message_id}/resources/{encoded_file_key}",
        destination,
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        params={"type": resource_type},
        timeout_seconds=timeout_seconds,
    )


def export_cloud_document(
    base_url: str,
    tenant_access_token: str,
    doc_type: str,
    token: str,
    file_extension: str,
    destination: Path,
    *,
    timeout_seconds: float = 30,
    poll_attempts: int = 20,
    poll_interval_seconds: float = 1,
) -> None:
    response = post_json(
        f"{base_url}/open-apis/drive/v1/export_tasks",
        {"file_extension": file_extension, "token": token, "type": doc_type},
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )
    ensure_lark_success(response, "create cloud document export task failed")

    ticket = (response.get("data") or {}).get("ticket")
    if not ticket:
        raise LarkApiError(f"missing export ticket in response: {response}")

    file_token = wait_export_file_token(
        base_url,
        tenant_access_token,
        ticket,
        token,
        timeout_seconds=timeout_seconds,
        poll_attempts=poll_attempts,
        poll_interval_seconds=poll_interval_seconds,
    )
    encoded_file_token = urllib.parse.quote(file_token, safe="")
    download_binary(
        f"{base_url}/open-apis/drive/v1/export_tasks/file/{encoded_file_token}/download",
        destination,
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )


def wait_export_file_token(
    base_url: str,
    tenant_access_token: str,
    ticket: str,
    original_token: str,
    *,
    timeout_seconds: float,
    poll_attempts: int,
    poll_interval_seconds: float,
) -> str:
    import time

    encoded_ticket = urllib.parse.quote(ticket, safe="")
    for _ in range(poll_attempts):
        response = get_json(
            f"{base_url}/open-apis/drive/v1/export_tasks/{encoded_ticket}",
            headers={"Authorization": f"Bearer {tenant_access_token}"},
            params={"token": original_token},
            timeout_seconds=timeout_seconds,
        )
        ensure_lark_success(response, "query cloud document export task failed")

        result = (response.get("data") or {}).get("result") or {}
        file_token = result.get("file_token") or result.get("token")
        if file_token:
            return file_token
        if result.get("job_status") in {"failed", "error"}:
            raise LarkApiError(f"cloud document export failed: {response}")
        time.sleep(poll_interval_seconds)

    raise LarkApiError(f"cloud document export timed out: ticket={ticket}")


def get_chat_name(
    base_url: str,
    tenant_access_token: str,
    chat_id: str,
    *,
    timeout_seconds: float = 5,
) -> str | None:
    response = get_json(
        f"{base_url}/open-apis/im/v1/chats/{urllib.parse.quote(chat_id, safe='')}",
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )
    ensure_lark_success(response, "get chat info failed")
    return (response.get("data") or {}).get("name") or None


def get_wiki_node_title(
    base_url: str,
    tenant_access_token: str,
    wiki_token: str,
    *,
    timeout_seconds: float = 5,
) -> str | None:
    response = get_json(
        f"{base_url}/open-apis/wiki/v2/spaces/get_node",
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        params={"token": wiki_token},
        timeout_seconds=timeout_seconds,
    )
    ensure_lark_success(response, "get wiki node title failed")
    node = ((response.get("data") or {}).get("node")) or {}
    return node.get("title") or None


def resolve_wiki_node(
    base_url: str,
    tenant_access_token: str,
    wiki_token: str,
    *,
    timeout_seconds: float = 10,
) -> tuple[str, str]:
    response = get_json(
        f"{base_url}/open-apis/wiki/v2/spaces/get_node",
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        params={"token": wiki_token},
        timeout_seconds=timeout_seconds,
    )
    ensure_lark_success(response, "resolve wiki node failed")

    node = ((response.get("data") or {}).get("node")) or {}
    obj_token = node.get("obj_token")
    obj_type = node.get("obj_type")
    if not obj_token or not obj_type:
        raise LarkApiError(f"wiki node response missing obj_token or obj_type: {response}")
    return obj_type, obj_token


def send_message(
    base_url: str,
    tenant_access_token: str,
    *,
    receive_id_type: str,
    receive_id: str,
    msg_type: str,
    content: dict[str, Any],
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    response = post_json(
        f"{base_url}/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
        {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": json.dumps(content, ensure_ascii=False),
        },
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        timeout_seconds=timeout_seconds,
    )

    if response.get("code") != 0:
        raise LarkApiError(f"send message failed: {response}")
    return response


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise LarkApiError(
            f"request lark api failed: {exc.code} {exc.reason}; body={response_body}"
        ) from exc

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LarkApiError(f"lark api returned non-json response: {response_body}") from exc


def get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout_seconds: float = 10,
) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        request_headers.update(headers)

    final_url = append_query(url, params)
    request = urllib.request.Request(final_url, headers=request_headers, method="GET")

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise LarkApiError(
            f"request lark api failed: {exc.code} {exc.reason}; body={response_body}"
        ) from exc

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LarkApiError(f"lark api returned non-json response: {response_body}") from exc


def download_binary(
    url: str,
    destination: Path,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout_seconds: float = 30,
) -> None:
    request_headers = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        request_headers.update(headers)

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        append_query(url, params),
        headers=request_headers,
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            with destination.open("wb") as file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    file.write(chunk)
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise LarkApiError(
            f"download lark file failed: {exc.code} {exc.reason}; body={response_body}"
        ) from exc


def append_query(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    query = urllib.parse.urlencode(
        {key: value for key, value in params.items() if value is not None}
    )
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{query}"


def ensure_lark_success(response: dict[str, Any], message: str) -> None:
    if response.get("code") != 0:
        raise LarkApiError(f"{message}: {response}")
