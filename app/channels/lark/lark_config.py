from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    lark_app_id: str
    lark_app_secret: str
    lark_open_api_base_url: str
    lark_default_chat_id: str | None
    enterprise_server_url: str
    enterprise_server_token: str | None
    forward_timeout_seconds: float
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_use_ssl: bool
    minio_bucket: str
    minio_raw_prefix: str
    qdrant_collection: str
    lark_bot_open_id: str | None
    rag_collection: str
    rag_collections: list[str]  # 多库检索的 collection 列表(为空则回退单个 rag_collection)
    rag_top_k: int
    rag_enable_rerank: bool
    rag_candidate_top_k: int
    bailian_api_key: str | None
    bailian_base_url: str
    bailian_model: str
    bailian_timeout_seconds: float
    # 并发兜底：固定 worker 数 + 有界队列上限。队列满时优雅拒绝，防止洪峰拖垮进程。
    rag_worker_count: int
    rag_queue_maxsize: int
    # 对话记忆（token 预算窗口 + 摘要）
    memory_rewrite_turns: int
    memory_summary_enabled: bool
    memory_summary_trigger_tokens: int
    memory_summary_max_tokens: int
    memory_ttl_seconds: int
    memory_max_sessions: int
    memory_persist_path: str | None  # SQLite 记忆持久化路径(空=纯内存，重启失忆)
    # Agent 工具调用（LangGraph 编排 Function Calling）
    rag_recall_quality_min: float  # 召回分数阈值：低于它视为召回不足(拒答/降级联网)
    rag_max_tool_rounds: int       # Agent 工具调用循环上限
    rag_enable_web_search: bool    # 知识库召回不足时是否降级联网搜索(需配 TAVILY_API_KEY)
    lark_streaming_card_enabled: bool
    lark_streaming_card_chunk_chars: int
    lark_streaming_card_flush_interval_seconds: float
    lark_streaming_card_min_delta_chars: int


def load_settings(*, require_enterprise_server: bool = True) -> Settings:
    load_dotenv()

    lark_app_id = require_env("LARK_APP_ID")
    lark_app_secret = require_env("LARK_APP_SECRET")
    if require_enterprise_server:
        enterprise_server_url = require_env("ENTERPRISE_SERVER_URL")
    else:
        enterprise_server_url = os.getenv("ENTERPRISE_SERVER_URL", "")

    return Settings(
        lark_app_id=lark_app_id,
        lark_app_secret=lark_app_secret,
        lark_open_api_base_url=os.getenv(
            "LARK_OPEN_API_BASE_URL", "https://open.feishu.cn"
        ).rstrip("/"),
        lark_default_chat_id=os.getenv("LARK_DEFAULT_CHAT_ID") or None,
        enterprise_server_url=enterprise_server_url,
        enterprise_server_token=os.getenv("ENTERPRISE_SERVER_TOKEN") or None,
        forward_timeout_seconds=float(os.getenv("FORWARD_TIMEOUT_SECONDS", "2.5")),
        minio_endpoint=os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
        minio_access_key=os.getenv("MINIO_ACCESS_KEY", ""),
        minio_secret_key=os.getenv("MINIO_SECRET_KEY", ""),
        minio_use_ssl=parse_bool(os.getenv("MINIO_USE_SSL", "false")),
        minio_bucket=os.getenv("MINIO_BUCKET", "knowledgebase"),
        minio_raw_prefix=os.getenv("MINIO_RAW_PREFIX", "raw"),
        qdrant_collection=os.getenv("QDRANT_COLLECTION", "knowledgebase"),
        lark_bot_open_id=os.getenv("LARK_BOT_OPEN_ID") or None,
        rag_collection=os.getenv(
            "RAG_COLLECTION", os.getenv("QDRANT_COLLECTION", "knowledgebase")
        ),
        rag_collections=[
            c.strip() for c in os.getenv("RAG_COLLECTIONS", "").split(",") if c.strip()
        ],
        rag_top_k=int(os.getenv("RAG_TOP_K", "5")),
        rag_enable_rerank=parse_bool(os.getenv("RAG_ENABLE_RERANK", "true")),
        rag_candidate_top_k=int(os.getenv("RAG_CANDIDATE_TOP_K", "50")),
        bailian_api_key=os.getenv("BAILIAN_API_KEY") or None,
        bailian_base_url=os.getenv(
            "BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/"),
        bailian_model=os.getenv("BAILIAN_MODEL", "deepseek-v4-pro"),
        bailian_timeout_seconds=float(os.getenv("BAILIAN_TIMEOUT_SECONDS", "60")),
        rag_worker_count=max(1, int(os.getenv("RAG_WORKER_COUNT", "10"))),
        rag_queue_maxsize=max(1, int(os.getenv("RAG_QUEUE_MAXSIZE", "50"))),
        memory_rewrite_turns=max(1, int(os.getenv("MEMORY_REWRITE_TURNS", "2"))),
        memory_summary_enabled=parse_bool(os.getenv("MEMORY_SUMMARY_ENABLED", "true")),
        memory_summary_trigger_tokens=max(1, int(os.getenv("MEMORY_SUMMARY_TRIGGER_TOKENS", "20000"))),
        memory_summary_max_tokens=max(1, int(os.getenv("MEMORY_SUMMARY_MAX_TOKENS", "2000"))),
        memory_ttl_seconds=max(60, int(os.getenv("MEMORY_TTL_SECONDS", "1800"))),
        memory_max_sessions=max(1, int(os.getenv("MEMORY_MAX_SESSIONS", "1000"))),
        memory_persist_path=os.getenv("MEMORY_PERSIST_PATH") or None,
        rag_recall_quality_min=float(os.getenv("RAG_RECALL_QUALITY_MIN", "0.68")),
        rag_max_tool_rounds=max(1, int(os.getenv("RAG_MAX_TOOL_ROUNDS", "4"))),
        rag_enable_web_search=parse_bool(os.getenv("RAG_ENABLE_WEB_SEARCH", "true")),
        lark_streaming_card_enabled=parse_bool(os.getenv("LARK_STREAMING_CARD_ENABLED", "false")),
        lark_streaming_card_chunk_chars=max(50, int(os.getenv("LARK_STREAMING_CARD_CHUNK_CHARS", "600"))),
        lark_streaming_card_flush_interval_seconds=max(
            0.0,
            float(os.getenv("LARK_STREAMING_CARD_FLUSH_INTERVAL_SECONDS", "0.5")),
        ),
        lark_streaming_card_min_delta_chars=max(
            1,
            int(os.getenv("LARK_STREAMING_CARD_MIN_DELTA_CHARS", "120")),
        ),
    )


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"缺少必要环境变量：{name}")
    return value


def parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}
