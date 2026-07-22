"""Pre-call guards for business database MCP tools."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.assistant.agent.tools.base import ToolContext
from infrastructure.mcp.config import env_bool


class BusinessQueryGuardError(RuntimeError):
    """Raised when a business query should not be sent to MCP."""


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: str
    message: str


_DATE_RANGE_PAIRS = (
    ("start_date", "end_date"),
    ("start_time", "end_time"),
    ("from_date", "to_date"),
    ("from_time", "to_time"),
    ("begin_date", "end_date"),
    ("begin_time", "end_time"),
    ("created_start", "created_end"),
    ("created_at_start", "created_at_end"),
    ("updated_start", "updated_end"),
    ("updated_at_start", "updated_at_end"),
)

_memory_lock = threading.Lock()
_memory_rate_windows: dict[str, list[float]] = {}


def enforce_business_query_guards(
    operation: str,
    arguments: dict[str, Any],
    ctx: ToolContext,
) -> None:
    """Validate structured tool arguments before calling the business MCP."""
    if not env_bool("BUSINESS_DB_QUERY_GUARD_ENABLED", default=True):
        return
    decision = evaluate_business_query(operation, arguments, ctx)
    if not decision.allowed:
        raise BusinessQueryGuardError(f"{decision.code}: {decision.message}")


def evaluate_business_query(
    operation: str,
    arguments: dict[str, Any],
    ctx: ToolContext,
) -> GuardDecision:
    max_days = _env_int("BUSINESS_DB_QUERY_MAX_WINDOW_DAYS", 30, minimum=1)
    date_decision = _check_date_window(arguments, max_days)
    if not date_decision.allowed:
        return date_decision

    limit = _env_int("BUSINESS_DB_QUERY_RATE_LIMIT_COUNT", 3, minimum=1)
    window_seconds = _env_int("BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1)
    caller = ctx.user_open_id or ctx.chat_id or "anonymous"
    key = f"business-db:{caller}"
    if not _allow_rate_limit(key, limit, window_seconds):
        return GuardDecision(
            allowed=False,
            code="RATE_LIMIT_EXCEEDED",
            message=(
                f"Business database query limit exceeded: at most {limit} calls "
                f"per {window_seconds} seconds."
            ),
        )

    return GuardDecision(allowed=True, code="ALLOW", message="Allowed")


def reset_business_query_guard_state() -> None:
    """Clear in-process guard state. Intended for tests."""
    with _memory_lock:
        _memory_rate_windows.clear()


def _check_date_window(arguments: dict[str, Any], max_days: int) -> GuardDecision:
    for start_key, end_key in _DATE_RANGE_PAIRS:
        start = _parse_datetime(arguments.get(start_key))
        end = _parse_datetime(arguments.get(end_key))
        if start is None or end is None:
            continue
        if end < start:
            return GuardDecision(
                allowed=False,
                code="INVALID_TIME_RANGE",
                message=f"{end_key} must be greater than or equal to {start_key}.",
            )
        if (end - start).total_seconds() > max_days * 24 * 60 * 60:
            return GuardDecision(
                allowed=False,
                code="TIME_RANGE_TOO_LARGE",
                message=f"Business database queries can cover at most {max_days} days.",
            )
    return GuardDecision(allowed=True, code="ALLOW", message="Allowed")


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.replace(tzinfo=None)
    return parsed


def _allow_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    redis_url = os.getenv("BUSINESS_DB_QUERY_GUARD_REDIS_URL", "").strip()
    if redis_url:
        redis_allowed = _allow_redis_rate_limit(redis_url, key, limit, window_seconds)
        if redis_allowed is not None:
            return redis_allowed
    return _allow_memory_rate_limit(key, limit, window_seconds)


def _allow_redis_rate_limit(
    redis_url: str,
    key: str,
    limit: int,
    window_seconds: int,
) -> bool | None:
    try:
        import redis
    except ImportError:
        return None
    try:
        client = redis.Redis.from_url(redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
        bucket = int(time.time() // window_seconds)
        redis_key = f"lark-agent:{key}:{bucket}"
        count = client.incr(redis_key)
        if count == 1:
            client.expire(redis_key, window_seconds + 5)
        return int(count) <= limit
    except Exception:
        return None


def _allow_memory_rate_limit(key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _memory_lock:
        calls = [ts for ts in _memory_rate_windows.get(key, []) if ts > cutoff]
        if len(calls) >= limit:
            _memory_rate_windows[key] = calls
            return False
        calls.append(now)
        _memory_rate_windows[key] = calls
        return True


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)
