from knowledge.retrieval.schemas import RecallResult

from app.assistant.agent.graph import AgentService


class _RecordingLLM:
    def __init__(self):
        self.messages_per_call = []

    def chat(self, *, messages, tools=None, tool_choice="auto", temperature=0.2):
        self.messages_per_call.append(messages)
        return {"role": "assistant", "content": "ok"}


class _EmptyRecaller:
    def search(self, request):
        return RecallResult(
            query=request.query,
            collection=request.collection,
            hits=[],
            total=0,
            latency_ms=1.0,
            model_dense="d",
            model_sparse="s",
        )


def _svc(llm):
    return AgentService(llm_client=llm, recaller=_EmptyRecaller(), collections=["c"])


def _has_business_skill(messages):
    return any("Runtime Skill: business_database_mcp" in str(m.get("content")) for m in messages)


def test_attaches_business_skill_for_authorized_keyword_request(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_SKILL_ENABLED", "true")
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")
    llm = _RecordingLLM()

    _svc(llm).answer("查一下 SKU-10086 的库存", user_open_id="ou_allowed", chat_type="p2p")

    assert _has_business_skill(llm.messages_per_call[0])


def test_does_not_attach_business_skill_to_next_unrelated_turn(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_SKILL_ENABLED", "true")
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")
    llm = _RecordingLLM()
    svc = _svc(llm)

    svc.answer("查一下 SKU-10086 的库存", user_open_id="ou_allowed", chat_type="p2p")
    svc.answer("报销流程怎么走", user_open_id="ou_allowed", chat_type="p2p")

    assert _has_business_skill(llm.messages_per_call[0])
    assert not _has_business_skill(llm.messages_per_call[1])


def test_does_not_attach_business_skill_in_group_chat(monkeypatch):
    monkeypatch.setenv("BUSINESS_DB_SKILL_ENABLED", "true")
    monkeypatch.setenv("BUSINESS_DB_MCP_ALLOWED_USERS", "ou_allowed")
    llm = _RecordingLLM()

    _svc(llm).answer("查一下 SKU-10086 的库存", user_open_id="ou_allowed", chat_type="group")

    assert not _has_business_skill(llm.messages_per_call[0])
