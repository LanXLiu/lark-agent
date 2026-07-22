"""从 MinIO raw 对象路径推断 Qdrant collection 名称。"""

from __future__ import annotations

DEFAULT_COLLECTIONS: tuple[str, ...] = (
    "knowledgebase",
    "rules",
    "dictionary",
    "cases",
    "exceptions",
    "company",
    "templates",
    "temporary",
)


def infer_collection_from_raw_key(
    raw_key: str,
    *,
    collections: list[str] | tuple[str, ...] | None = None,
    fallback: str = "temporary",
) -> str:
    """``raw/<collection>/path/to/file`` → ``collection``；无法识别时返回 fallback。"""
    allowed = set(collections or DEFAULT_COLLECTIONS)
    parts = raw_key.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "raw":
        candidate = parts[1]
        if candidate in allowed:
            return candidate
    return fallback if fallback in allowed else "temporary"
