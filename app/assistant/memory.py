"""对话记忆层（token 预算窗口 + 摘要）。

跨通道通用的短期对话记忆：记住每个用户在每个会话里的多轮问答，为
「指代消解（改写）」和「答案连贯（生成）」提供上下文。

- **token 预算窗口**：保留最近若干轮全文，累计 token 一旦超过 summary_trigger_tokens，
  就把最早的老轮次摘进 summary，直到剩余全文 token 回落到预算内；
- **摘要**：被挤出预算的老轮次不直接丢，而是增量压缩进 summary（调一次 LLM），
  远处梗概 + 近处细节都在，喂给大模型的上下文 token 始终可控；
- **两种视图**：改写只需要最近 1-2 轮（指代几乎总指刚说过的东西，带太长反而
  把检索词带偏）；生成用「摘要 + 预算内的全文轮次」以求连贯。

设计要点：
- 会话 key = f"{chat_id}:{user_open_id}" —— 群聊按「人」分，避免多人上下文串味；
- TTL 过期：超时无活动视为新话题，取历史时清空；
- 全局会话数上界 + LRU 淘汰，防内存无限增长；
- 线程安全：问答跑在多 worker 线程，可能并发读写；
- 摘要 LLM 失败时兜底为「只保留预算内轮次」，绝不影响主问答流程。
"""

from __future__ import annotations

import functools
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol, TYPE_CHECKING

from app.assistant.prompts.memory import (
    FLUSH_FACTS_SYSTEM,
    FLUSH_FACTS_USER_TMPL,
    SUMMARY_SYSTEM_TMPL,
    SUMMARY_USER_TMPL,
)

if TYPE_CHECKING:
    from app.assistant.memory_store import SQLiteMemoryStore

# ---- 默认参数（均可经 Settings/env 覆盖，见 configure()）----
DEFAULT_REWRITE_TURNS = 2              # 改写用的历史轮数（短）
DEFAULT_SUMMARY_ENABLED = True         # 是否开启摘要（关掉则退化为纯 token 预算窗口）
DEFAULT_SUMMARY_TRIGGER_TOKENS = 20000  # 全文轮次累计 token 超过它才开始摘老对话
DEFAULT_TTL_SECONDS = 30 * 60          # 会话过期：无活动多久视为新话题
DEFAULT_MAX_SESSIONS = 1000            # 全局会话上限
DEFAULT_SUMMARY_MAX_TOKENS = 2000      # 摘要长度上限（token；防摘要本身膨胀）
_TIKTOKEN_ENCODING = "cl100k_base"     # 百炼是 deepseek/qwen，无官方编码，用通用近似

# 「至少留一轮全文」的下限：即便单轮就超预算，也保留最近这一轮，否则近处细节全丢。
_MIN_KEEP_TURNS = 1


@functools.lru_cache(maxsize=1)
def _encoder():
    """惰性加载并缓存 tiktoken 编码器（加载较慢，进程内复用；只读，线程安全）。"""
    import tiktoken

    return tiktoken.get_encoding(_TIKTOKEN_ENCODING)


def count_tokens(text: str) -> int:
    """估算一段文本的 token 数。tiktoken 不可用时退化为按字符近似（不致命）。"""
    if not text:
        return 0
    try:
        return len(_encoder().encode(text))
    except Exception:  # noqa: BLE001 —— 编码失败不能影响主流程，退化为字符近似
        return len(text)


def _turn_tokens(turn: tuple[str, str]) -> int:
    q, a = turn
    return count_tokens(q) + count_tokens(a)


class SummarizerLLM(Protocol):
    """摘要所需的最小 LLM 接口，与 BailianChatClient.complete 兼容。"""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


@dataclass
class AnswerContext:
    """生成答案时用的上下文视图：一段前情摘要 + 最近若干轮全文。"""

    summary: str = ""
    recent_turns: list[tuple[str, str]] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.summary and not self.recent_turns


@dataclass
class _Session:
    turns: list[tuple[str, str]] = field(default_factory=list)  # 预算内保留全文的轮次
    summary: str = ""                                           # 被摘进摘要的老对话
    summarized_count: int = 0                                   # 已被摘进 summary 的轮数
    last_active: float = 0.0                                    # monotonic 时间（内存 TTL 判断用）
    last_active_wall: float = 0.0                               # wall-clock 时间（持久化/重启后判过期用）
    summarizing: bool = False                                   # 是否已有一次摘要在飞（同 key 串行化）


class ConversationMemory:
    """进程内对话记忆。token 预算窗口 + 可选摘要。线程安全。"""

    def __init__(
        self,
        *,
        rewrite_turns: int = DEFAULT_REWRITE_TURNS,
        summary_enabled: bool = DEFAULT_SUMMARY_ENABLED,
        summary_trigger_tokens: int = DEFAULT_SUMMARY_TRIGGER_TOKENS,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        summary_max_tokens: int = DEFAULT_SUMMARY_MAX_TOKENS,
        summarizer: SummarizerLLM | None = None,
        store: "SQLiteMemoryStore | None" = None,
    ) -> None:
        self.rewrite_turns = max(1, rewrite_turns)
        self.summary_enabled = summary_enabled
        self.summary_trigger_tokens = max(1, summary_trigger_tokens)
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.summary_max_tokens = max(1, summary_max_tokens)
        self.summarizer = summarizer
        self.store = store
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = threading.Lock()
        if store is not None:
            self._load_from_store()

    def _load_from_store(self) -> None:
        """启动时从持久化后端读回未过期会话到内存（重启不失忆）。"""
        try:
            persisted = self.store.load_all(ttl_seconds=self.ttl_seconds)
        except Exception:  # noqa: BLE001 —— 读回失败不影响启动，退化为空内存
            return
        now_mono = time.monotonic()
        now_wall = time.time()
        for ps in persisted:
            # wall-clock 记录会话「多久前活跃」，据此把 last_active(monotonic) 回填成
            # 等价的过去时刻，让内存 TTL 判断在重启后仍然正确。
            age = max(0.0, now_wall - ps.last_active_wall)
            self._sessions[ps.key] = _Session(
                turns=list(ps.turns),
                summary=ps.summary,
                summarized_count=ps.summarized_count,
                last_active=now_mono - age,
                last_active_wall=ps.last_active_wall,
            )

    def set_summarizer(self, summarizer: SummarizerLLM | None) -> None:
        """注入摘要用 LLM（bot 启动时用问答同一个客户端注入）。"""
        self.summarizer = summarizer

    @staticmethod
    def make_key(chat_id: str | None, user_open_id: str | None) -> str:
        return f"{chat_id or '?'}:{user_open_id or '?'}"

    # ---- 读：两种视图 ----

    def get_for_rewrite(self, key: str) -> list[tuple[str, str]]:
        """改写（指代消解）用：只给最近 rewrite_turns 轮全文，不带摘要。"""
        session = self._live_session(key)
        if session is None:
            return []
        return list(session.turns[-self.rewrite_turns:])

    def get_for_answer(self, key: str) -> AnswerContext:
        """生成答案用：前情摘要 + 预算内的全文轮次。

        turns 的累计 token 已被 append_turn 控制在 summary_trigger_tokens 附近，
        故这里直接整体返回，无需再按轮数裁。
        """
        session = self._live_session(key)
        if session is None:
            return AnswerContext()
        return AnswerContext(
            summary=session.summary,
            recent_turns=list(session.turns),
        )

    # ---- 写 ----

    def append_turn(self, key: str, question: str, answer: str) -> None:
        """存一轮问答；累计 token 超预算时把最早的老轮次滚进摘要（若开启）。"""
        now = time.monotonic()
        now_wall = time.time()
        # 摘要要调 LLM，可能慢——在锁外算，锁内只做快速的数据更新。
        with self._lock:
            session = self._sessions.get(key) or _Session()
            session.turns.append((question, answer))
            session.last_active = now
            session.last_active_wall = now_wall
            self._sessions[key] = session
            self._sessions.move_to_end(key)
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)

            summary_available = self.summary_enabled and self.summarizer is not None
            # 需要摘要的前提：摘要可用、当前没有摘要在飞（同 key 串行化）、
            # 且全文累计 token 已超预算。溢出的老轮次数量由 token 动态决定。
            overflow: list[tuple[str, str]] = []
            if summary_available and not session.summarizing:
                split_idx = self._overflow_split_index(session.turns)
                if split_idx > 0:
                    overflow = session.turns[:split_idx]
                    old_summary = session.summary
                    session.summarizing = True  # 占坑：摘要期间别的 append 不再重复触发

            if not overflow and not summary_available:
                # 摘要不可用（没开启 / 没注入 LLM）：无法压缩老对话，只能按 token
                # 预算裁掉最早的轮次防膨胀（至少保留最近 _MIN_KEEP_TURNS 轮）。
                split_idx = self._overflow_split_index(session.turns)
                if split_idx > 0:
                    del session.turns[:split_idx]

        if not overflow:
            self._persist(key)
            return

        # flush：摘要压缩前，先从「将被压缩的老轮次」抽取关键事实，防摘要丢硬信息。
        facts = self._flush_facts(overflow)
        new_summary = self._summarize(old_summary, overflow, facts)

        with self._lock:
            s = self._sessions.get(key)
            if s is None:
                return
            try:
                if new_summary is not None:
                    s.summary = self._truncate_to_tokens(new_summary, self.summary_max_tokens)
                    # 只砍掉「确实摘进摘要的那 n 轮」，从头删。摘要期间（锁外）可能有
                    # 新轮次追加到末尾；因同 key 串行化，overflow 不会与别的摘要区间
                    # 重叠，del 前 n 轮是安全且精确的（新轮次都在末尾，不受影响）。
                    n = min(len(overflow), len(s.turns))
                    del s.turns[:n]
                    s.summarized_count += n
                else:
                    # 摘要失败兜底：不丢信息也不无限涨——这次先不摘（下轮再试）。
                    # 仅当全文 token 涨到硬上限（预算 3 倍）时才硬裁，防失败反复导致膨胀。
                    if self._total_tokens(s.turns) > self.summary_trigger_tokens * 3:
                        split_idx = self._overflow_split_index(s.turns)
                        if split_idx > 0:
                            del s.turns[:split_idx]
            finally:
                s.summarizing = False  # 无论成败都释放占坑，否则该 key 再不会摘要
        self._persist(key)

    def clear(self, key: str) -> None:
        with self._lock:
            self._sessions.pop(key, None)
        if self.store is not None:
            self.store.delete(key)

    def _persist(self, key: str) -> None:
        """把某会话的当前状态落盘（store 为 None 时空操作）。锁内取快照，锁外写盘。"""
        if self.store is None:
            return
        with self._lock:
            s = self._sessions.get(key)
            if s is None:
                return
            snapshot = (list(s.turns), s.summary, s.summarized_count, s.last_active_wall)
        self.store.save_session(key, *snapshot)

    # ---- 内部：token 预算计算 ----

    @staticmethod
    def _total_tokens(turns: list[tuple[str, str]]) -> int:
        return sum(_turn_tokens(t) for t in turns)

    def _overflow_split_index(self, turns: list[tuple[str, str]]) -> int:
        """返回「应摘掉的最早若干轮」的边界下标 split_idx。

        规则：从最新一轮往回累加 token，尽量多保留最近的轮次，直到再加一轮就超
        预算为止；更早的轮次即为溢出（overflow = turns[:split_idx]）。至少保留最近
        _MIN_KEEP_TURNS 轮（哪怕单轮就超预算，也不摘光近处细节）。返回 0 表示无需摘。
        """
        n = len(turns)
        if n <= _MIN_KEEP_TURNS:
            return 0
        if self._total_tokens(turns) <= self.summary_trigger_tokens:
            return 0
        kept = 0
        keep_count = 0
        # 从后往前累加，决定保留多少最近轮次
        for turn in reversed(turns):
            t = _turn_tokens(turn)
            if keep_count >= _MIN_KEEP_TURNS and kept + t > self.summary_trigger_tokens:
                break
            kept += t
            keep_count += 1
        split_idx = n - keep_count
        return max(0, split_idx)

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """把摘要截断到 max_tokens 以内（按编码器切片，失败则按字符近似）。"""
        if not text:
            return text
        try:
            enc = _encoder()
            ids = enc.encode(text)
            if len(ids) <= max_tokens:
                return text
            return enc.decode(ids[:max_tokens])
        except Exception:  # noqa: BLE001 —— 截断失败退化为字符近似，绝不影响主流程
            return text[: max_tokens * 2]

    # ---- 内部 ----

    def _live_session(self, key: str) -> _Session | None:
        """取未过期的会话；过期则删除并返回 None。命中则刷新 LRU。"""
        now = time.monotonic()
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            if now - session.last_active > self.ttl_seconds:
                del self._sessions[key]
                return None
            self._sessions.move_to_end(key)
            return session

    def _flush_facts(self, overflow: list[tuple[str, str]]) -> str:
        """flush：摘要压缩前，从「将被压缩的老轮次」抽取关键事实（防摘要丢硬信息）。

        返回一段「关键事实」文本（每行一条）；LLM 不可用/失败时返回空串（跳过，不影响摘要）。
        """
        if self.summarizer is None:
            return ""
        try:
            convo = "\n".join(f"用户：{q}\n助手：{a}" for q, a in overflow)
            system_prompt = FLUSH_FACTS_SYSTEM
            user_prompt = FLUSH_FACTS_USER_TMPL.format(convo=convo)
            out = (
                self.summarizer.complete(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )
                or ""
            ).strip()
            return out
        except Exception:  # noqa: BLE001 —— flush 失败不影响摘要主流程
            return ""

    def _summarize(
        self,
        old_summary: str,
        overflow: list[tuple[str, str]],
        facts: str = "",
    ) -> str | None:
        """把「已有摘要 + flush 抽出的关键事实 + 新溢出的老轮次」增量压缩成新摘要。失败返回 None。"""
        if self.summarizer is None:
            return None
        try:
            convo = "\n".join(f"用户：{q}\n助手：{a}" for q, a in overflow)
            prev = f"已有摘要：\n{old_summary}\n\n" if old_summary else ""
            facts_block = f"必须保留的关键事实（逐条并入摘要，不要丢）：\n{facts}\n\n" if facts else ""
            # 给 LLM 一个直观的字数提示（token 上限按经验约等于 0.75 倍字数），
            # 实际仍以 _truncate_to_tokens 按 token 硬截断为准。
            approx_chars = int(self.summary_max_tokens * 0.75)
            system_prompt = SUMMARY_SYSTEM_TMPL.format(approx_chars=approx_chars)
            user_prompt = SUMMARY_USER_TMPL.format(
                prev=prev, facts_block=facts_block, convo=convo
            )
            out = (
                self.summarizer.complete(
                    system_prompt=system_prompt, user_prompt=user_prompt
                )
                or ""
            ).strip()
            return out or None
        except Exception:  # noqa: BLE001 —— 摘要失败绝不能影响主问答
            return None


# ---- 进程级单例 + 模块级便捷函数 ----

_memory = ConversationMemory()


def configure(
    *,
    rewrite_turns: int | None = None,
    summary_enabled: bool | None = None,
    summary_trigger_tokens: int | None = None,
    ttl_seconds: int | None = None,
    max_sessions: int | None = None,
    summary_max_tokens: int | None = None,
    summarizer: SummarizerLLM | None = None,
    persist_path: str | None = None,
) -> None:
    """用配置重建单例（bot 启动时调一次）。仅覆盖显式传入的项。

    persist_path 非空时，用 SQLite 持久化对话记忆（重启不失忆）；为空则纯内存。
    """
    global _memory
    current = _memory
    store = None
    if persist_path:
        from app.assistant.memory_store import SQLiteMemoryStore

        store = SQLiteMemoryStore(persist_path)
    _memory = ConversationMemory(
        rewrite_turns=rewrite_turns if rewrite_turns is not None else current.rewrite_turns,
        summary_enabled=summary_enabled if summary_enabled is not None else current.summary_enabled,
        summary_trigger_tokens=summary_trigger_tokens if summary_trigger_tokens is not None else current.summary_trigger_tokens,
        ttl_seconds=ttl_seconds if ttl_seconds is not None else current.ttl_seconds,
        max_sessions=max_sessions if max_sessions is not None else current.max_sessions,
        summary_max_tokens=summary_max_tokens if summary_max_tokens is not None else current.summary_max_tokens,
        summarizer=summarizer if summarizer is not None else current.summarizer,
        store=store,
    )


def set_summarizer(summarizer: SummarizerLLM | None) -> None:
    _memory.set_summarizer(summarizer)


def make_key(chat_id: str | None, user_open_id: str | None) -> str:
    return ConversationMemory.make_key(chat_id, user_open_id)


def get_for_rewrite(key: str) -> list[tuple[str, str]]:
    return _memory.get_for_rewrite(key)


def get_for_answer(key: str) -> AnswerContext:
    return _memory.get_for_answer(key)


def append_turn(key: str, question: str, answer: str) -> None:
    _memory.append_turn(key, question, answer)
