from __future__ import annotations

from app.channels.lark.feedback import STREAMING_ANSWER_ELEMENT_ID
from app.channels.lark.feedback import build_streaming_answer_card
from app.channels.lark.feedback import build_streaming_final_card
from app.channels.lark.feedback import iter_streaming_prefixes
from app.channels.lark.feedback import StreamingCardThrottler
from app.channels.lark import lark_api


def test_streaming_answer_card_uses_json_2_streaming_mode() -> None:
    card = build_streaming_answer_card("正在处理...")

    assert card["schema"] == "2.0"
    assert card["config"]["streaming_mode"] is True
    element = card["body"]["elements"][0]
    assert element["tag"] == "markdown"
    assert element["element_id"] == STREAMING_ANSWER_ELEMENT_ID


def test_streaming_final_card_keeps_feedback_values() -> None:
    card = build_streaming_final_card("答案", "trace-1", "ou_xxx")
    elements = card["body"]["elements"]

    assert card["config"]["streaming_mode"] is False
    buttons = [element for element in elements if element.get("tag") == "button"]
    assert [button["text"]["content"] for button in buttons] == ["有用", "没用"]
    assert buttons[0]["behaviors"][0]["value"]["trace_id"] == "trace-1"
    assert buttons[0]["behaviors"][0]["value"]["asker"] == "ou_xxx"
    assert buttons[0]["behaviors"][0]["value"]["vote"] == "up"
    assert buttons[1]["behaviors"][0]["value"]["vote"] == "down"


def test_iter_streaming_prefixes_returns_incremental_prefixes() -> None:
    assert iter_streaming_prefixes("abcdef", 2) == ["ab", "abcd", "abcdef"]
    assert iter_streaming_prefixes("", 2) == [""]


def test_streaming_card_throttler_batches_by_delta_chars() -> None:
    clock_value = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return clock_value

    def sleeper(seconds: float) -> None:
        nonlocal clock_value
        sleeps.append(seconds)
        clock_value += seconds

    throttler = StreamingCardThrottler(
        min_interval_seconds=0.5,
        min_delta_chars=3,
        clock=clock,
        sleeper=sleeper,
    )

    prefixes = list(throttler.iter_prefixes("abcdefghij", 1))

    assert prefixes == ["abc", "abcdef", "abcdefghi", "abcdefghij"]
    assert sleeps == [0.5, 0.5, 0.5]


def test_streaming_card_throttler_should_flush_small_chunks_only_when_forced() -> None:
    throttler = StreamingCardThrottler(
        min_interval_seconds=0,
        min_delta_chars=5,
    )
    assert throttler.should_flush("ab")
    throttler.mark_flushed("ab")
    assert not throttler.should_flush("abcd")
    assert throttler.should_flush("abcd", force=True)


def test_update_card_markdown_element_payload(monkeypatch) -> None:
    calls: list[tuple[str, str, dict, dict | None]] = []

    def fake_put_json(url, payload, *, headers=None, timeout_seconds=5):
        calls.append(("PUT", url, payload, headers))
        return {"code": 0}

    monkeypatch.setattr(lark_api, "put_json", fake_put_json)

    lark_api.update_card_markdown_element(
        "https://open.feishu.cn",
        "tenant-token",
        "card-1",
        STREAMING_ANSWER_ELEMENT_ID,
        "hello",
        sequence=3,
        uuid="uuid-1",
    )

    method, url, payload, headers = calls[0]
    assert method == "PUT"
    assert url.endswith(f"/open-apis/cardkit/v1/cards/card-1/elements/{STREAMING_ANSWER_ELEMENT_ID}/content")
    assert payload == {"content": "hello", "sequence": 3, "uuid": "uuid-1"}
    assert headers == {"Authorization": "Bearer tenant-token"}
