"""service/memory.py 的单元测试。

聚焦「改动时最容易被弄坏、且线上会静默丢上下文」的行为：
- token 预算窗口 / 摘要视图的基本正确性；
- 摘要触发按 token 累计（超 summary_trigger_tokens 才摘最早的老轮次）；
- 摘要期间并发插入新轮次不被误删（回归哨兵）；
- 摘要 LLM 失败时的兜底（保留近处、不丢、不无限增长）；
- TTL 过期与 LRU 淘汰。

为让 token 计数完全可预测，用 monkeypatch 把 count_tokens 替成「每字符 1 token」，
测试文本长度即 token 数，与 tiktoken 的具体编码解耦。
"""

from __future__ import annotations

import pytest

import service.memory as memory
from service.memory import ConversationMemory


@pytest.fixture(autouse=True)
def _char_is_one_token(monkeypatch):
    """把 token 计数固定为「1 字符 = 1 token」，让阈值行为可精确预测。"""
    monkeypatch.setattr(memory, "count_tokens", lambda text: len(text or ""))
    # _truncate_to_tokens 内部用 tiktoken 编解码，这里也退化成按字符切，避免依赖真实编码。
    monkeypatch.setattr(
        ConversationMemory,
        "_truncate_to_tokens",
        lambda self, text, max_tokens: (text or "")[:max_tokens],
    )


class _FakeSummarizer:
    """可控假摘要器：记录被调用次数，返回一段固定摘要。"""

    def __init__(self, output: str = "SUMMARY") -> None:
        self.output = output
        self.calls = 0

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        return self.output


class _FailingSummarizer:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        raise RuntimeError("模拟百炼摘要接口挂了")


def _turn(qlen: int, alen: int = 0) -> tuple[str, str]:
    """构造 token 数已知的一轮（q 用 'x'*qlen，a 用 'y'*alen）。"""
    return ("x" * qlen, "y" * alen)


def _mem(**kw) -> ConversationMemory:
    base = dict(rewrite_turns=2, summary_enabled=False,
                summary_trigger_tokens=100, ttl_seconds=1000, max_sessions=100)
    base.update(kw)
    return ConversationMemory(**base)


# ---- 基本视图 ----

def test_空会话两种视图都为空():
    mem = _mem()
    assert mem.get_for_rewrite("k") == []
    assert mem.get_for_answer("k").is_empty()


def test_改写视图只给最近rewrite_turns轮():
    mem = _mem(rewrite_turns=2, summary_trigger_tokens=10_000)
    for i in range(5):
        mem.append_turn("k", f"问{i}", f"答{i}")
    assert mem.get_for_rewrite("k") == [("问3", "答3"), ("问4", "答4")]


def test_生成视图返回预算内的全部全文():
    mem = _mem(summary_trigger_tokens=10_000)  # 阈值很大，不触发裁剪
    for i in range(5):
        mem.append_turn("k", f"问{i}", f"答{i}")
    ctx = mem.get_for_answer("k")
    assert len(ctx.recent_turns) == 5
    assert ctx.summary == ""


def test_不同会话key互不串味():
    mem = _mem(summary_trigger_tokens=10_000)
    mem.append_turn("chat:userA", "A问", "A答")
    mem.append_turn("chat:userB", "B问", "B答")
    assert mem.get_for_rewrite("chat:userA") == [("A问", "A答")]
    assert mem.get_for_rewrite("chat:userB") == [("B问", "B答")]


# ---- token 触发摘要 ----

def test_累计token超过阈值才生成摘要():
    fake = _FakeSummarizer()
    # 阈值 100 token。每轮 40 token（q=40）。第 3 轮累计 120 > 100 → 触发。
    mem = _mem(summary_enabled=True, summary_trigger_tokens=100, summarizer=fake)
    mem.append_turn("k", _turn(40)[0], "")   # 40
    mem.append_turn("k", _turn(40)[0], "")   # 80
    assert fake.calls == 0                   # 还没超 100
    mem.append_turn("k", _turn(40)[0], "")   # 120 > 100 → 摘
    assert fake.calls >= 1
    ctx = mem.get_for_answer("k")
    assert ctx.summary == "SUMMARY"
    # 摘掉最早一轮后，剩余全文 token 应回落到阈值内
    remaining = sum(len(q) + len(a) for q, a in ctx.recent_turns)
    assert remaining <= 100


def test_摘要开启时老轮次进摘要而非被丢弃():
    """回归哨兵：老对话应被摘进 summary，不能被静默丢弃。"""
    fake = _FakeSummarizer()
    mem = _mem(summary_enabled=True, summary_trigger_tokens=100, summarizer=fake)
    for _ in range(20):
        mem.append_turn("k", "x" * 30, "")   # 每轮 30 token，连塞 20 轮
    assert fake.calls > 0, "摘要从未触发"
    assert mem.get_for_answer("k").summary != ""
    # 预算内留存的 token 不超阈值（老的都进了摘要）
    ctx = mem.get_for_answer("k")
    remaining = sum(len(q) + len(a) for q, a in ctx.recent_turns)
    assert remaining <= 100


def test_摘要关闭时按token裁掉最早轮次防膨胀():
    mem = _mem(summary_enabled=False, summary_trigger_tokens=100)
    for _ in range(20):
        mem.append_turn("k", "x" * 30, "")
    ctx = mem.get_for_answer("k")
    assert ctx.summary == ""  # 没开摘要
    remaining = sum(len(q) + len(a) for q, a in ctx.recent_turns)
    assert remaining <= 100   # 但仍被裁到预算内


def test_单轮就超预算也至少保留最近一轮():
    mem = _mem(summary_enabled=False, summary_trigger_tokens=50)
    mem.append_turn("k", "x" * 500, "")  # 单轮 500 token，远超预算
    ctx = mem.get_for_answer("k")
    assert len(ctx.recent_turns) == 1   # 不能摘光，至少留最近这轮


# ---- 回归哨兵：摘要期间并发插入 ----

def test_摘要期间并发插入的新轮次不被误删():
    """真实线程复现：线程A 触发摘要（锁外、慢）期间，线程B 对同会话 append。
    修复保证：同 key 摘要串行化 + 收尾只 del 精确的 n 轮 → 一轮都不丢。
    """
    import threading

    started = threading.Event()
    release = threading.Event()

    class _SlowSummarizer:
        def complete(self, *, system_prompt: str, user_prompt: str) -> str:
            started.set()
            release.wait(2)
            return "SUM"

    # 阈值 100；每轮 40 token。塞 3 轮(120)触发摘要，摘最早 1 轮。
    mem = _mem(summary_enabled=True, summary_trigger_tokens=100,
               summarizer=_SlowSummarizer())
    mem.append_turn("k", "A" * 40, "")
    mem.append_turn("k", "B" * 40, "")

    def _thread_a() -> None:
        mem.append_turn("k", "C" * 40, "")  # 第3轮触发摘要，卡住

    ta = threading.Thread(target=_thread_a)
    ta.start()
    assert started.wait(2), "摘要未进入锁外阶段"
    mem.append_turn("k", "D" * 40, "")      # 摘要进行中，并发插入
    release.set()
    ta.join(2)

    session = mem._sessions["k"]
    heads = [q[0] for q, _ in session.turns]  # 每轮首字母标识
    assert "A" not in heads, "最早一轮应已摘进摘要"
    # B、C、D 三轮必须都在，一轮不丢
    assert "B" in heads and "C" in heads and "D" in heads, f"轮次丢失：{heads}"
    assert session.summarizing is False, "摘要占坑标志未复位"


# ---- 摘要失败兜底 ----

def test_摘要失败时不丢近处对话():
    mem = _mem(summary_enabled=True, summary_trigger_tokens=100,
               summarizer=_FailingSummarizer())
    for i in range(6):
        mem.append_turn("k", f"问{i}" + "x" * 30, "")
    ctx = mem.get_for_answer("k")
    heads = [q for q, _ in ctx.recent_turns]
    assert any("问5" in q for q in heads)  # 最近一轮必须还在
    assert ctx.summary == ""               # 摘要没成功


def test_摘要持续失败也不会无限增长():
    mem = _mem(summary_enabled=True, summary_trigger_tokens=100,
               summarizer=_FailingSummarizer())
    for _ in range(200):
        mem.append_turn("k", "x" * 30, "")
    ctx = mem.get_for_answer("k")
    total = sum(len(q) + len(a) for q, a in ctx.recent_turns)
    # 兜底硬上限是阈值的 3 倍
    assert total <= 100 * 3


# ---- TTL / LRU ----

def test_ttl过期视为新话题():
    mem = _mem(ttl_seconds=60, summary_trigger_tokens=10_000)
    mem.append_turn("k", "旧问", "旧答")
    mem._sessions["k"].last_active -= 10_000  # 拨到很久以前
    assert mem.get_for_rewrite("k") == []
    assert mem.get_for_answer("k").is_empty()


def test_超过max_sessions时淘汰最久未用的会话():
    mem = _mem(max_sessions=2, summary_trigger_tokens=10_000)
    mem.append_turn("a", "qa", "aa")
    mem.append_turn("b", "qb", "ab")
    mem.append_turn("c", "qc", "ac")
    assert mem.get_for_rewrite("a") == []
    assert mem.get_for_rewrite("b") == [("qb", "ab")]
    assert mem.get_for_rewrite("c") == [("qc", "ac")]


def test_clear删除指定会话():
    mem = _mem(summary_trigger_tokens=10_000)
    mem.append_turn("k", "问", "答")
    mem.clear("k")
    assert mem.get_for_rewrite("k") == []


# ---- SQLite 持久化（重启不失忆）----

def test_sqlite持久化后重建能读回会话(tmp_path):
    from service.memory_store import SQLiteMemoryStore
    db = str(tmp_path / "mem.db")

    store1 = SQLiteMemoryStore(db)
    mem1 = ConversationMemory(summary_enabled=False, summary_trigger_tokens=10_000,
                              ttl_seconds=10_000, store=store1)
    mem1.append_turn("chat:u1", "报销流程是什么", "先提单再审批")
    mem1.append_turn("chat:u1", "多久到账", "3个工作日")

    # 模拟进程重启：新建 store + memory，从同一个 db 读回
    store2 = SQLiteMemoryStore(db)
    mem2 = ConversationMemory(summary_enabled=False, summary_trigger_tokens=10_000,
                              ttl_seconds=10_000, store=store2)
    turns = mem2.get_for_rewrite("chat:u1")
    assert ("多久到账", "3个工作日") in turns          # 重启后仍读得到
    assert mem2.get_for_answer("chat:u1").recent_turns  # 有历史


def test_clear同时删除持久化(tmp_path):
    from service.memory_store import SQLiteMemoryStore
    db = str(tmp_path / "mem.db")
    store = SQLiteMemoryStore(db)
    mem = ConversationMemory(summary_enabled=False, summary_trigger_tokens=10_000,
                             ttl_seconds=10_000, store=store)
    mem.append_turn("k", "问", "答")
    mem.clear("k")
    # 重建后不应再读到
    mem2 = ConversationMemory(summary_enabled=False, summary_trigger_tokens=10_000,
                              ttl_seconds=10_000, store=SQLiteMemoryStore(db))
    assert mem2.get_for_rewrite("k") == []


def test_持久化的过期会话重启后不读回(tmp_path):
    import time as _t
    from service.memory_store import SQLiteMemoryStore
    db = str(tmp_path / "mem.db")
    store = SQLiteMemoryStore(db)
    # 直接写一条 last_active_wall 在很久以前的会话
    store.save_session("old", [("q", "a")], "", 0, _t.time() - 10_000)
    mem = ConversationMemory(summary_enabled=False, ttl_seconds=60, store=store)  # ttl=60s
    assert mem.get_for_rewrite("old") == []  # 过期，重启不读回


# ---- flush：摘要压缩前抽取关键事实 ----

def test_flush在摘要前被调用且事实并入摘要():
    # 用一个能区分「flush 抽事实」和「摘要」两种调用的假摘要器
    class _FactAwareSummarizer:
        def __init__(self):
            self.calls = []
        def complete(self, *, system_prompt, user_prompt):
            self.calls.append(system_prompt)
            if "事实提取助手" in system_prompt:
                return "- 报销上限 500 元"          # flush 抽到的事实
            return "摘要正文（含前情）"               # 摘要
    fake = _FactAwareSummarizer()
    mem = _mem(summary_enabled=True, summary_trigger_tokens=100, summarizer=fake)
    for _ in range(20):
        mem.append_turn("k", "x" * 30, "")           # 堆到触发摘要
    # flush 和 summarize 都被调过（system_prompt 里分别含「事实提取助手」和「摘要助手」）
    assert any("事实提取助手" in s for s in fake.calls)
    assert any("对话摘要助手" in s for s in fake.calls)
    assert mem.get_for_answer("k").summary != ""
