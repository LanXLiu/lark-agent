"""Agent 问答可观测性：把每次 @机器人 问答记录成一条结构化 JSONL 日志。

设计原则：**日志记录绝不能影响主问答流程**——所有写盘用 try 包住，
失败只 warning，不抛异常，问答照常进行。

每次问答对应一个 QaTrace 实例，记录问题、召回结果、分数、来源、
分阶段耗时、成败原因，最终追加一行 JSON 到 logs/qa_trace.jsonl。
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# 日志落地路径：项目根目录下 logs/qa_trace.jsonl（logs/ 已被 .gitignore 忽略）
_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "qa_trace.jsonl"
_WRITE_LOCK = threading.Lock()


class QaTrace:
    """单次问答的追踪记录器。

    用法::

        trace = QaTrace(chat_id, user_open_id, question)
        ...
        trace.mark_recall(hit_count=3, top_score=0.74, sources=[...])
        trace.mark_llm(answer_chars=156)
        trace.set_stage("success")
        trace.finish()   # 落盘，出口处统一调用一次

    stage 取值：empty_question / no_api_key / token_fail /
    recall_empty / recall_fail / llm_fail / success
    """

    def __init__(self, chat_id: str | None, user_open_id: str | None, question: str) -> None:
        self.trace_id = uuid.uuid4().hex[:8]
        self.chat_id = chat_id
        self.user_open_id = user_open_id
        self.question = question
        self._t0 = time.perf_counter()
        self.stage: str = "unknown"
        self.recall_hit_count: int | None = None
        self.recall_top_score: float | None = None
        self.sources: list[str] = []
        self.answer_chars: int | None = None
        self.recall_ms: float | None = None
        self.llm_ms: float | None = None
        self.rewrite_ms: float | None = None
        self.rewritten_question: str | None = None
        self.error: str | None = None
        self._finished = False

    def set_stage(self, stage: str) -> None:
        self.stage = stage

    def set_error(self, message: str) -> None:
        self.error = (message or "")[:500]

    def set_rewrite(
        self, original: str, rewritten: str, rewrite_ms: float | None = None
    ) -> None:
        """记录多轮 query 改写：原问题已在 self.question，这里记改写后的与耗时。"""
        self.rewritten_question = rewritten
        if rewrite_ms is not None:
            self.rewrite_ms = rewrite_ms

    def mark_recall(
        self,
        *,
        hit_count: int,
        top_score: float | None,
        sources: list[str],
        recall_ms: float | None = None,
    ) -> None:
        self.recall_hit_count = hit_count
        self.recall_top_score = top_score
        self.sources = sources
        if recall_ms is not None:
            self.recall_ms = recall_ms

    def mark_llm(self, *, answer_chars: int, llm_ms: float | None = None) -> None:
        self.answer_chars = answer_chars
        if llm_ms is not None:
            self.llm_ms = llm_ms

    def finish(self) -> None:
        """组装记录并追加落盘。可安全多次调用，只写一次。"""
        if self._finished:
            return
        self._finished = True

        total_ms = round((time.perf_counter() - self._t0) * 1000, 1)
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "trace_id": self.trace_id,
            "chat_id": self.chat_id,
            "user_open_id": self.user_open_id,
            "question": self.question,
            "rewritten_question": self.rewritten_question,
            "stage": self.stage,
            "recall_hit_count": self.recall_hit_count,
            "recall_top_score": self.recall_top_score,
            "sources": self.sources,
            "answer_chars": self.answer_chars,
            "latency_ms": {
                "rewrite": _round_or_none(self.rewrite_ms),
                "recall": _round_or_none(self.recall_ms),
                "llm": _round_or_none(self.llm_ms),
                "total": total_ms,
            },
            "error": self.error,
        }
        _append_jsonl(record)


def _now_iso() -> str:
    """本地时间 ISO 字符串（飞书机器人为常驻 app，datetime.now 可用）。"""
    return datetime.now().isoformat(timespec="seconds")


def _round_or_none(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


def _append_jsonl(record: dict[str, Any]) -> None:
    """线程安全地追加一行 JSON；任何失败都不向上抛，只 warning。"""
    try:
        line = json.dumps(record, ensure_ascii=False)
        with _WRITE_LOCK:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                f.flush()
    except Exception as exc:  # noqa: BLE001 —— 可观测性绝不能影响主流程
        LOGGER.warning("写入 qa_trace 日志失败（忽略，不影响问答）：%s", exc)
