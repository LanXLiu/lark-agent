from __future__ import annotations

import pytest

from app.assistant.agent.tools.base import ToolContext
from app.assistant.agent.tools.business_guards import (
    BusinessQueryGuardError,
    enforce_business_query_guards,
    evaluate_business_query,
    reset_business_query_guard_state,
)


@pytest.fixture(autouse=True)
def _reset_guard(monkeypatch):
    reset_business_query_guard_state()
    monkeypatch.delenv("BUSINESS_DB_QUERY_GUARD_REDIS_URL", raising=False)
    monkeypatch.setenv("BUSINESS_DB_QUERY_GUARD_ENABLED", "true")
    monkeypatch.setenv("BUSINESS_DB_QUERY_MAX_WINDOW_DAYS", "30")
    monkeypatch.setenv("BUSINESS_DB_QUERY_RATE_LIMIT_COUNT", "3")
    monkeypatch.setenv("BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS", "60")
    yield
    reset_business_query_guard_state()


def test_allows_time_window_at_maximum():
    decision = evaluate_business_query(
        "order_status",
        {"start_date": "2026-01-01", "end_date": "2026-01-31"},
        ToolContext(user_open_id="ou_1"),
    )

    assert decision.allowed is True


def test_rejects_time_window_over_maximum():
    decision = evaluate_business_query(
        "order_status",
        {"start_date": "2026-01-01", "end_date": "2026-02-01"},
        ToolContext(user_open_id="ou_1"),
    )

    assert decision.allowed is False
    assert decision.code == "TIME_RANGE_TOO_LARGE"


def test_rejects_inverted_time_window():
    decision = evaluate_business_query(
        "order_status",
        {"start_time": "2026-02-01T00:00:00", "end_time": "2026-01-01T00:00:00"},
        ToolContext(user_open_id="ou_1"),
    )

    assert decision.allowed is False
    assert decision.code == "INVALID_TIME_RANGE"


def test_rate_limits_business_queries_per_user():
    ctx = ToolContext(user_open_id="ou_rate_limited")

    for _ in range(3):
        enforce_business_query_guards("inventory_lookup", {"sku": "SKU-1"}, ctx)

    with pytest.raises(BusinessQueryGuardError, match="RATE_LIMIT_EXCEEDED"):
        enforce_business_query_guards("inventory_lookup", {"sku": "SKU-1"}, ctx)


def test_rate_limit_isolated_by_user():
    for index in range(3):
        enforce_business_query_guards(
            "inventory_lookup",
            {"sku": "SKU-1"},
            ToolContext(user_open_id=f"ou_{index}"),
        )

    enforce_business_query_guards(
        "inventory_lookup",
        {"sku": "SKU-1"},
        ToolContext(user_open_id="ou_new"),
    )
