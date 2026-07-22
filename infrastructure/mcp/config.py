"""Small environment helpers shared by MCP clients and servers."""

from __future__ import annotations

import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str, default: str = "") -> set[str]:
    return {item.strip() for item in os.getenv(name, default).split(",") if item.strip()}


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is not configured: {name}")
    return value


def required_env_int(name: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = required_env(name)
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise RuntimeError(f"Environment variable {name} must be >= {minimum}{upper}")
    return value


def required_env_float(name: str, *, minimum: float = 0.1) -> float:
    raw = required_env(name)
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be a number") from exc
    if value < minimum:
        raise RuntimeError(f"Environment variable {name} must be >= {minimum}")
    return value
