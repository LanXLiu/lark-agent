"""recall 单次覆盖开关的单测(parent_child / rerank 的三态解析)。

只测纯方法 _use_parent_child / _use_rerank,不触发 __init__ 的重依赖
(qdrant/encoder/reranker)——用 object.__new__ 绕过构造,手动塞假 config。
"""

from __future__ import annotations

from dataclasses import dataclass

from recall.hybrid_recall import HybridRecaller
from recall.schemas import RecallRequest


@dataclass
class _FakeConfig:
    parent_child_enabled: bool = True
    rerank_enabled: bool = True


def _recaller(cfg: _FakeConfig) -> HybridRecaller:
    r = object.__new__(HybridRecaller)  # 绕过 __init__，只测纯方法
    r.config = cfg
    return r


def _req(**kw) -> RecallRequest:
    return RecallRequest(query="q", collection="c", **kw)


# ---- parent_child 三态 ----

def test_parent_child_none_走全局配置_开():
    r = _recaller(_FakeConfig(parent_child_enabled=True))
    assert r._use_parent_child(_req(parent_child=None)) is True


def test_parent_child_none_走全局配置_关():
    r = _recaller(_FakeConfig(parent_child_enabled=False))
    assert r._use_parent_child(_req(parent_child=None)) is False


def test_parent_child_true_强制开_即使全局关():
    r = _recaller(_FakeConfig(parent_child_enabled=False))
    assert r._use_parent_child(_req(parent_child=True)) is True


def test_parent_child_false_强制关_即使全局开():
    r = _recaller(_FakeConfig(parent_child_enabled=True))
    assert r._use_parent_child(_req(parent_child=False)) is False


# ---- rerank 三态(回归,确认没动坏)----

def test_rerank_none_走全局():
    r = _recaller(_FakeConfig(rerank_enabled=True))
    assert r._use_rerank(_req(enable_rerank=None)) is True


def test_rerank_单次覆盖():
    r = _recaller(_FakeConfig(rerank_enabled=True))
    assert r._use_rerank(_req(enable_rerank=False)) is False
