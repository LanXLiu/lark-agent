"""通用指数退避重试。

只对「值得重试」的瞬时错误退避重试：HTTP 429（限流）、5xx（服务端错误）、
超时、连接错误。业务错误（4xx 中除 429、参数错误等）立即抛出，不浪费重试。

主要给打百炼（DashScope）的三处远程调用用：LLM 生成/改写/摘要、embedding、
rerank——高并发时它们可能偶发 429，退避重试能把瞬时限流「熨平」，避免直接
变成用户看到的失败。

同时兼容两套 HTTP 栈：
- ``urllib``（LLM 客户端用）：urllib.error.HTTPError.code / URLError；
- ``httpx``（embedding / rerank 用）：HTTPStatusError.response.status_code /
  TimeoutException / TransportError。
"""

from __future__ import annotations

import random
import time
import urllib.error
from typing import Callable, TypeVar

from loguru import logger

T = TypeVar("T")

# 判定为「可重试」的 HTTP 状态码：限流 + 服务端错误
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _status_of(exc: BaseException) -> int | None:
    """从各种异常里尽量抠出 HTTP 状态码；抠不到返回 None。"""
    # urllib
    if isinstance(exc, urllib.error.HTTPError):
        return int(getattr(exc, "code", 0)) or None
    # httpx（延迟导入，避免硬依赖）
    try:
        import httpx

        if isinstance(exc, httpx.HTTPStatusError):
            return int(exc.response.status_code)
    except ImportError:
        pass
    return None


def is_retryable(exc: BaseException) -> bool:
    """瞬时、值得重试的错误才返回 True。"""
    status = _status_of(exc)
    if status is not None:
        return status in _RETRYABLE_STATUS

    # urllib 的超时/连接错误（URLError 包裹 socket.timeout 等）
    if isinstance(exc, urllib.error.URLError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    # httpx 的超时/传输层错误
    try:
        import httpx

        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
    except ImportError:
        pass

    return False


def retry_call(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    jitter: float = 0.3,
    what: str = "远程调用",
) -> T:
    """执行 fn；遇到可重试错误则指数退避重试，最多 max_attempts 次。

    - 不可重试错误：立即抛出（不浪费重试）。
    - 重试耗尽：抛出最后一次的异常。
    - 退避：base_delay * 2**(n-1)，封顶 max_delay，叠加随机抖动防止「重试风暴」。
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 —— 需按类型判断是否重试
            if attempt >= max_attempts or not is_retryable(exc):
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            delay += random.uniform(0, jitter)
            logger.warning(
                "{} 第 {}/{} 次失败（{}），{:.2f}s 后重试",
                what,
                attempt,
                max_attempts,
                type(exc).__name__,
                delay,
            )
            time.sleep(delay)
