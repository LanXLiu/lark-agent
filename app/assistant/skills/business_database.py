"""Business database skill activation and prompt rendering."""

from __future__ import annotations

import os
import re
from functools import lru_cache

from app.assistant.agent.tools.base import ToolContext
from app.assistant.skills.loader import AssistantSkill, load_skill
from infrastructure.mcp.config import env_bool, env_csv

BUSINESS_DATABASE_SKILL_FILE = "business_database_mcp.md"

_SKU_RE = re.compile(r"\b(?:SKU[-_A-Za-z0-9]*|[A-Z]{1,8}[-_]\d{2,}[A-Z0-9-_]*)\b", re.I)
_ORDER_RE = re.compile(r"\b(?:SO|PO|ORDER|ORD)[-_]?\d{4,}[A-Z0-9-_]*\b", re.I)
_BUSINESS_KEYWORDS = (
    "库存",
    "现货",
    "可售",
    "仓库",
    "订单",
    "发货",
    "物流",
    "签收",
    "商品",
    "产品",
    "型号",
    "类目",
    "sku",
    "stock",
    "inventory",
    "order",
    "shipment",
    "delivery",
    "product",
)


def business_database_skill_context(question: str, ctx: ToolContext) -> str | None:
    """Return a one-turn system prompt when the business database skill should guide the agent."""
    if not env_bool("BUSINESS_DB_SKILL_ENABLED", default=True):
        return None
    if not _can_attach_business_skill(ctx):
        return None
    if not looks_like_business_database_request(question):
        return None
    return render_business_database_skill_context(_load_business_skill())


def looks_like_business_database_request(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    if any(keyword.lower() in lowered for keyword in _BUSINESS_KEYWORDS):
        return True
    return bool(_SKU_RE.search(raw) or _ORDER_RE.search(raw))


def render_business_database_skill_context(skill: AssistantSkill) -> str:
    return "\n".join(
        [
            "[Runtime Skill: business_database_mcp]",
            skill.summary.strip(),
            "",
            "Use this skill only for the current user request. Do not carry it into later turns unless it is attached again.",
            "",
            skill.content.strip(),
        ]
    )


def _can_attach_business_skill(ctx: ToolContext) -> bool:
    if ctx.chat_type != "p2p":
        return False
    allowed_users = env_csv("BUSINESS_DB_MCP_ALLOWED_USERS")
    return bool(ctx.user_open_id and ctx.user_open_id in allowed_users)


@lru_cache(maxsize=1)
def _load_business_skill() -> AssistantSkill:
    filename = os.getenv("BUSINESS_DB_SKILL_FILE", BUSINESS_DATABASE_SKILL_FILE).strip()
    return load_skill(filename or BUSINESS_DATABASE_SKILL_FILE)

