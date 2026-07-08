"""对话记忆的 SQLite 持久化后端（重启/崩溃不丢多轮上下文）。

用 Python 标准库 sqlite3（无需安装、无独立进程、无网络），把每个会话的
turns / summary 落到一个本地 `.db` 文件；bot 启动时读回，重启不失忆。

设计要点：
- **wall-clock 时间**：last_active 存绝对时间戳（time.time()），因为进程重启后
  time.monotonic() 会归零，持久化必须用可跨重启比较的绝对时间；
- **线程安全**：问答跑在多 worker 线程，用一把锁串行化 DB 写，且连接按需开关
  （sqlite3 连接不宜跨线程共享）；
- **失败不致命**：任何 DB 异常只吞掉记日志，绝不影响主问答（记忆持久化是增强，不是命脉）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PersistedSession:
    """从 DB 读回的一个会话快照（与 memory._Session 的可持久字段对应）。"""

    key: str
    turns: list[tuple[str, str]]
    summary: str
    summarized_count: int
    last_active_wall: float  # 绝对时间戳（秒）


class SQLiteMemoryStore:
    """对话记忆的 SQLite 持久化。零依赖、零运维、单文件。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        # 每次操作开一个连接（sqlite3 连接不宜跨线程共享）；WAL 提升并发读写。
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        key              TEXT PRIMARY KEY,
                        turns_json       TEXT NOT NULL,
                        summary          TEXT NOT NULL,
                        summarized_count INTEGER NOT NULL,
                        last_active_wall REAL NOT NULL,
                        updated_at       REAL NOT NULL
                    )
                    """
                )
        except Exception:  # noqa: BLE001 —— 建表失败不影响主流程（退化为纯内存）
            logger.exception("SQLiteMemoryStore: 初始化表失败，持久化将不可用")

    def save_session(
        self,
        key: str,
        turns: list[tuple[str, str]],
        summary: str,
        summarized_count: int,
        last_active_wall: float,
    ) -> None:
        """落盘一个会话（upsert）。失败只记日志，不抛。"""
        try:
            turns_json = json.dumps(turns, ensure_ascii=False)
            with self._lock, self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sessions
                        (key, turns_json, summary, summarized_count, last_active_wall, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        turns_json=excluded.turns_json,
                        summary=excluded.summary,
                        summarized_count=excluded.summarized_count,
                        last_active_wall=excluded.last_active_wall,
                        updated_at=excluded.updated_at
                    """,
                    (key, turns_json, summary, summarized_count, last_active_wall, time.time()),
                )
        except Exception:  # noqa: BLE001
            logger.warning("SQLiteMemoryStore: 保存会话失败（忽略）key=%s", key)

    def delete(self, key: str) -> None:
        try:
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE key=?", (key,))
        except Exception:  # noqa: BLE001
            logger.warning("SQLiteMemoryStore: 删除会话失败（忽略）key=%s", key)

    def load_all(self, ttl_seconds: float | None = None) -> list[PersistedSession]:
        """读回全部会话；给定 ttl_seconds 时，用 wall-clock 过滤掉已过期的。"""
        out: list[PersistedSession] = []
        now = time.time()
        try:
            with self._lock, self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, turns_json, summary, summarized_count, last_active_wall FROM sessions"
                ).fetchall()
        except Exception:  # noqa: BLE001
            logger.exception("SQLiteMemoryStore: 读回会话失败，按空处理")
            return out
        for key, turns_json, summary, cnt, last_active in rows:
            if ttl_seconds is not None and now - last_active > ttl_seconds:
                continue  # 重启时顺带跳过已过期会话
            try:
                turns = [tuple(t) for t in json.loads(turns_json)]
            except Exception:  # noqa: BLE001 —— 单条损坏跳过，不影响其它
                continue
            out.append(PersistedSession(
                key=key, turns=turns, summary=summary,
                summarized_count=int(cnt), last_active_wall=float(last_active),
            ))
        return out
