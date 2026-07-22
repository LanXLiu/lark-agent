"""Agent 答案的「安静反馈」：带 👍/👎 按钮的卡片 + 反馈落盘。

群聊场景设计：
- 卡片是群里共享的同一条消息，按钮不替换、不消失，群里任何人都能点；
- 点击仅给点击者弹 toast，不影响他人；
- 反馈按 (trace_id, user_open_id) 去重——每人各记一份，同人改投覆盖自己
  （写入时不去重，统计阶段按最后一条覆盖）；
- 记录 is_asker（点击者是否为提问者），统计时可区分。

反馈记录落盘 logs/qa_feedback.jsonl，靠 trace_id 与问答日志 qa_trace.jsonl 关联。
原则同 observability：写盘失败绝不影响主流程。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# 按钮 value 里的 action 标识，回调时据此识别是反馈点击
FEEDBACK_ACTION = "qa_feedback"

_FEEDBACK_PATH = Path(__file__).resolve().parent.parent / "logs" / "qa_feedback.jsonl"
_WRITE_LOCK = threading.Lock()


def build_feedback_card(answer_text: str, trace_id: str, asker_open_id: str | None) -> dict[str, Any]:
    """构造带 👍/👎 反馈按钮的飞书交互卡片。

    Args:
        answer_text: 已组织好的答案文本（含「引用来源」段落）。
        trace_id: 本次问答的 trace_id，塞进按钮 value，用于关联反馈。
        asker_open_id: 提问者 open_id，塞进按钮 value，回调时判断点击者是否为提问者。

    Returns:
        飞书 interactive 卡片的 dict（msg_type=interactive 的 content）。
    """
    base_value = {
        "action": FEEDBACK_ACTION,
        "trace_id": trace_id,
        "asker": asker_open_id or "",
    }
    return {
        "config": {"wide_screen_mode": True},
        "elements": [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": answer_text},
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "👍 有用"},
                        "type": "default",
                        "value": {**base_value, "vote": "up"},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "👎 没用"},
                        "type": "default",
                        "value": {**base_value, "vote": "down"},
                    },
                ],
            },
        ],
    }


def record_feedback(
    trace_id: str,
    vote: str,
    user_open_id: str | None,
    is_asker: bool,
) -> None:
    """追加一条反馈记录到 logs/qa_feedback.jsonl（线程安全，失败不抛）。

    写入时不去重；同一 (trace_id, user_open_id) 的多次点击都追加，
    由统计阶段取最后一条实现「同人改投覆盖」。
    """
    try:
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "trace_id": trace_id,
            "vote": vote,
            "user_open_id": user_open_id,
            "is_asker": is_asker,
        }
        line = json.dumps(record, ensure_ascii=False)
        with _WRITE_LOCK:
            _FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _FEEDBACK_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
    except Exception as exc:  # noqa: BLE001 —— 反馈记录失败不能影响主流程
        LOGGER.warning("写入 qa_feedback 日志失败（忽略）：%s", exc)
