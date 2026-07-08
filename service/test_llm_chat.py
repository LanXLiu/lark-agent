"""BailianChatClient.chat 的单测(mock post_json,不发真实请求)。"""

from __future__ import annotations

import service.llm_client as llm_mod
from service.llm_client import BailianChatClient


def _client() -> BailianChatClient:
    return BailianChatClient(api_key="x", base_url="http://fake/v1", model="deepseek-v4-pro")


def test_chat_传tools时payload含tools和tool_choice(monkeypatch):
    captured = {}

    def fake_post(url, payload, *, api_key, timeout_seconds):
        captured["payload"] = payload
        return {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    monkeypatch.setattr(llm_mod, "post_json", fake_post)
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    _client().chat(messages=[{"role": "user", "content": "q"}], tools=tools, tool_choice="auto")

    assert captured["payload"]["tools"] == tools
    assert captured["payload"]["tool_choice"] == "auto"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "q"}]


def test_chat_不传tools时payload无tools字段(monkeypatch):
    captured = {}

    def fake_post(url, payload, *, api_key, timeout_seconds):
        captured["payload"] = payload
        return {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}

    monkeypatch.setattr(llm_mod, "post_json", fake_post)
    _client().chat(messages=[{"role": "user", "content": "q"}])
    assert "tools" not in captured["payload"]
    assert "tool_choice" not in captured["payload"]


def test_chat_返回完整message含tool_calls(monkeypatch):
    msg = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "思考...",
        "tool_calls": [
            {"id": "call_1", "function": {"name": "search_knowledge",
                                          "arguments": '{"query": "报销"}'}}
        ],
    }
    monkeypatch.setattr(llm_mod, "post_json",
                        lambda *a, **k: {"choices": [{"message": msg}]})
    out = _client().chat(messages=[{"role": "user", "content": "q"}], tools=[{"x": 1}])
    # 返回原始 message dict(不 strip、不取 content),tool_calls 原样带回
    assert out == msg
    assert out["tool_calls"][0]["function"]["name"] == "search_knowledge"


def test_chat_无choices抛错(monkeypatch):
    monkeypatch.setattr(llm_mod, "post_json", lambda *a, **k: {"choices": []})
    try:
        _client().chat(messages=[{"role": "user", "content": "q"}])
        assert False, "应抛 RuntimeError"
    except RuntimeError:
        pass
