from app.assistant.agent.tools.base import ToolContext
from app.assistant.skills import SkillLoader
from app.assistant.skills.business_database import (
    business_database_skill_context,
    looks_like_business_database_request,
)


def test_business_database_skill_loads():
    skill = SkillLoader().load("business_database_mcp.md")

    assert skill.name == "business_database_mcp"
    assert skill.version
    assert "business database MCP" in skill.summary
    assert "# Business Database MCP Skill" in skill.content


def test_business_database_skill_defines_expected_tool_rules():
    skill = SkillLoader().load("business_database_mcp.md")

    assert skill.tool_rule("inventory_lookup")["required_all"] == ["sku"]
    assert skill.tool_rule("order_status")["required_all"] == ["order_no"]
    assert skill.tool_rule("product_lookup")["required_all"] == ["keyword"]


def test_business_database_skill_records_hard_guard_contract():
    skill = SkillLoader().load("business_database_mcp.md")

    constraints = skill.data["shared_constraints"]
    assert constraints["no_sql_generation"] is True
    assert constraints["max_window_days"] == 30
    assert constraints["rate_limit"] == {"max_calls": 3, "window_seconds": 60}


def test_business_database_skill_keyword_detection():
    assert looks_like_business_database_request("帮我查一下 SKU-10086 的库存")
    assert looks_like_business_database_request("订单 SO20260722001 发货了吗")
    assert looks_like_business_database_request("这个产品型号是什么")
    assert not looks_like_business_database_request("报销流程怎么走")


def test_business_database_skill_context_requires_authorized_private_chat(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_SKILL_ENABLED", "true")
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")

    allowed = ToolContext(user_open_id="ou_allowed", chat_type="p2p")
    group = ToolContext(user_open_id="ou_allowed", chat_type="group")
    other_user = ToolContext(user_open_id="ou_other", chat_type="p2p")

    assert business_database_skill_context("查一下 SKU-1 库存", allowed)
    assert business_database_skill_context("报销流程怎么走", allowed) is None
    assert business_database_skill_context("查一下 SKU-1 库存", group) is None
    assert business_database_skill_context("查一下 SKU-1 库存", other_user) is None

