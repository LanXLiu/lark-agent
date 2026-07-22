from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from knowledge.utils.retry import retry_call


class BailianChatClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        # 结构化输出（如 {"type": "json_object"}）：让网关强制模型只吐合法 JSON。
        # 可选——不传则行为与之前完全一致。
        if response_format is not None:
            payload["response_format"] = response_format
        response = post_json(
            f"{self.base_url}/chat/completions",
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM returned no choices: {response}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError(f"LLM returned empty content: {response}")
        return str(content).strip()

    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """多轮对话 + 原生工具调用。返回完整的 assistant message（原始 dict）。

        与 complete 的区别：吃完整 messages 数组、可传 tools，返回整个 message
        （含 content / tool_calls / 可能的 reasoning_content），供 Agent 循环原样
        判断 tool_calls 并把它 append 回 messages。

        注意（deepseek 思考模式）：tool_choice 只支持 "auto"/"none"，不要传具名或
        "required"；把本方法返回的 message append 回 messages 前，调用方需剥掉
        reasoning_content（见 app/assistant/agent/graph.py 的 _strip_reasoning）。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        response = post_json(
            f"{self.base_url}/chat/completions",
            payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
        )
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM returned no choices: {response}")
        return choices[0].get("message") or {}


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    def _do_request() -> str:
        # 注意：HTTPError 在此处向上抛（带 .code），供 retry 判定 429/5xx；
        # 只有「重试耗尽或不可重试」时才在下面转成 RuntimeError。
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")

    try:
        body = retry_call(_do_request, what="百炼 LLM 请求")
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: {exc.code} {exc.reason}; body={err_body}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM returned non-JSON response: {body}") from exc
