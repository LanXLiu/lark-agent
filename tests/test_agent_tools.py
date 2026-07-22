"""Unit tests for the agent tool registry and core tool behavior."""

from __future__ import annotations

from app.assistant.agent.tools import registry
from app.assistant.agent.tools.base import ToolContext, ToolResult
from knowledge.retrieval.schemas import RecallHit, RecallResult


class _FakeRecaller:
    """Record the last RecallRequest and return one deterministic hit."""

    def __init__(self):
        self.last_request = None

    def search(self, request):
        self.last_request = request
        hit = RecallHit(
            id="1",
            score=0.9,
            content="Reimbursement requires submitting an approval first.",
            doc_uuid="d1",
            chunk_index=0,
            collection="c",
            breadcrumb="Finance Policy > Reimbursement",
            filename="finance-policy.md",
        )
        return RecallResult(
            query=request.query,
            collection=request.collection,
            hits=[hit],
            total=1,
            latency_ms=1.0,
            model_dense="d",
            model_sparse="s",
        )


def test_registers_core_tools():
    names = {tool["function"]["name"] for tool in registry.tool_schemas()}
    assert "search_knowledge" in names
    assert "get_current_time" in names


def test_merges_multiple_collections_and_keeps_top_scores():
    searched = []

    class _MultiRecaller:
        def search(self, request):
            searched.append(request.collection)
            scores = {"a": 0.7, "b": 0.9, "c": 0.5}
            score = scores.get(request.collection, 0.0)
            hit = RecallHit(
                id=request.collection,
                score=score,
                content=f"content-{request.collection}",
                doc_uuid=f"d_{request.collection}",
                chunk_index=0,
                collection=request.collection,
                filename="x.md",
            )
            return RecallResult(
                query=request.query,
                collection=request.collection,
                hits=[hit],
                total=1,
                latency_ms=1.0,
                model_dense="d",
                model_sparse="s",
            )

    ctx = ToolContext(recaller=_MultiRecaller(), collections=["a", "b", "c"], top_k=2)
    result = registry.execute("search_knowledge", {"query": "q"}, ctx)
    assert set(searched) == {"a", "b", "c"}
    assert len(result.hits) == 2
    assert result.hits[0].score == 0.9
    assert result.hits[1].score == 0.7


def test_schema_excludes_runtime_identity_fields():
    for tool in registry.tool_schemas():
        props = tool["function"]["parameters"].get("properties", {})
        assert "user_open_id" not in props
        assert "chat_id" not in props
        assert "recaller" not in props


class _FakeBusinessTool:
    name = "inventory_lookup"
    description = "Query inventory."
    parameters = {
        "type": "object",
        "properties": {"sku": {"type": "string"}},
        "required": ["sku"],
        "additionalProperties": False,
    }
    permission_group = "business_db"

    def run(self, args, ctx):
        return ToolResult(text="called")


def test_business_mcp_tool_is_hidden_without_authorized_private_chat(monkeypatch):
    registry.register_tool_instance(_FakeBusinessTool())
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")

    no_user = ToolContext(chat_type="p2p")
    unauthorized_user = ToolContext(user_open_id="ou_other", chat_type="p2p")
    group_chat = ToolContext(user_open_id="ou_allowed", chat_type="group")

    assert "inventory_lookup" not in _schema_names(registry.tool_schemas(no_user))
    assert "inventory_lookup" not in _schema_names(registry.tool_schemas(unauthorized_user))
    assert "inventory_lookup" not in _schema_names(registry.tool_schemas(group_chat))


def test_business_mcp_tool_is_visible_for_authorized_private_chat(monkeypatch):
    registry.register_tool_instance(_FakeBusinessTool())
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")

    ctx = ToolContext(user_open_id="ou_allowed", chat_type="p2p")

    assert "inventory_lookup" in _schema_names(registry.tool_schemas(ctx))


def test_business_mcp_tool_execute_is_denied_outside_authorized_private_chat(monkeypatch):
    registry.register_tool_instance(_FakeBusinessTool())
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")

    result = registry.execute(
        "inventory_lookup",
        {"sku": "SKU-1"},
        ToolContext(user_open_id="ou_allowed", chat_type="group"),
    )

    assert "Permission denied" in result.text


def _schema_names(schemas):
    return {tool["function"]["name"] for tool in schemas}


def test_search_knowledge_returns_text_and_hits():
    recaller = _FakeRecaller()
    ctx = ToolContext(recaller=recaller, collections=["c"], top_k=5)
    result = registry.execute("search_knowledge", {"query": "reimbursement flow"}, ctx)
    assert "Reimbursement requires submitting" in result.text
    assert len(result.hits) == 1
    assert recaller.last_request.query == "reimbursement flow"


def test_include_context_maps_to_parent_child_retrieval():
    recaller = _FakeRecaller()
    ctx = ToolContext(recaller=recaller, collections=["c"], top_k=5)
    registry.execute("search_knowledge", {"query": "architecture", "include_context": True}, ctx)
    assert recaller.last_request.parent_child is True

    registry.execute("search_knowledge", {"query": "architecture"}, ctx)
    assert recaller.last_request.parent_child is False


def test_get_current_time_does_not_require_recaller():
    result = registry.execute("get_current_time", {}, ToolContext())
    assert "当前时间" in result.text
    assert result.hits == []


def test_unknown_tool_returns_error_text():
    result = registry.execute("no_such_tool", {}, ToolContext())
    assert "未知工具" in result.text


def test_collection_recall_failure_is_isolated():
    class Boom:
        def search(self, request):
            raise RuntimeError("boom")

    ctx = ToolContext(recaller=Boom(), collections=["c"])
    result = registry.execute("search_knowledge", {"query": "x"}, ctx)
    assert result.hits == []
    assert "未在知识库检索到相关内容" in result.text
