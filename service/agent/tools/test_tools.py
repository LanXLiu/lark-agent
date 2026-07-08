"""Agent 工具层单测:注册、schema、执行、身份不进 schema、父子召回映射。"""

from __future__ import annotations

from recall.schemas import RecallHit, RecallResult
from service.agent.tools import registry
from service.agent.tools.base import ToolContext


class _FakeRecaller:
    """记录收到的 RecallRequest,返回固定命中。"""

    def __init__(self):
        self.last_request = None

    def search(self, request):
        self.last_request = request
        hit = RecallHit(id="1", score=0.9, content="报销需先提单审批",
                        doc_uuid="d1", chunk_index=0, collection="c",
                        breadcrumb="财务制度 > 报销", filename="财务制度.md")
        return RecallResult(query=request.query, collection=request.collection,
                            hits=[hit], total=1, latency_ms=1.0,
                            model_dense="d", model_sparse="s")


def test_两个工具都注册了():
    names = {t["function"]["name"] for t in registry.tool_schemas()}
    assert "search_knowledge" in names
    assert "get_current_time" in names


def test_多collection检索合并并按分数排序取topk():
    # 三个 collection 各返回一条不同分数的命中，应全部被检索、合并后按分数降序取 top_k。
    searched = []

    class _MultiRecaller:
        def search(self, request):
            searched.append(request.collection)
            scores = {"a": 0.7, "b": 0.9, "c": 0.5}
            s = scores.get(request.collection, 0.0)
            hit = RecallHit(id=request.collection, score=s, content=f"内容{request.collection}",
                            doc_uuid=f"d_{request.collection}", chunk_index=0,
                            collection=request.collection, filename="x.md")
            return RecallResult(query=request.query, collection=request.collection,
                                hits=[hit], total=1, latency_ms=1.0,
                                model_dense="d", model_sparse="s")

    ctx = ToolContext(recaller=_MultiRecaller(), collections=["a", "b", "c"], top_k=2)
    res = registry.execute("search_knowledge", {"query": "q"}, ctx)
    assert set(searched) == {"a", "b", "c"}           # 三个库都查了
    assert len(res.hits) == 2                          # 全局取 top_k=2
    assert res.hits[0].score == 0.9 and res.hits[1].score == 0.7  # 按分数降序



def test_schema里不含身份字段():
    for t in registry.tool_schemas():
        props = t["function"]["parameters"].get("properties", {})
        assert "user_open_id" not in props
        assert "chat_id" not in props
        assert "recaller" not in props


def test_search_knowledge_执行返回文本和hits():
    rec = _FakeRecaller()
    ctx = ToolContext(recaller=rec, collections=["c"], top_k=5)
    res = registry.execute("search_knowledge", {"query": "报销流程"}, ctx)
    assert "报销需先提单审批" in res.text
    assert len(res.hits) == 1
    assert rec.last_request.query == "报销流程"


def test_include_context_映射到parent_child():
    rec = _FakeRecaller()
    ctx = ToolContext(recaller=rec, collections=["c"], top_k=5)
    registry.execute("search_knowledge", {"query": "架构", "include_context": True}, ctx)
    assert rec.last_request.parent_child is True

    registry.execute("search_knowledge", {"query": "架构"}, ctx)  # 默认 false
    assert rec.last_request.parent_child is False


def test_get_current_time_无需recaller():
    res = registry.execute("get_current_time", {}, ToolContext())
    assert "当前时间" in res.text
    assert res.hits == []


def test_未知工具返回错误文本不抛():
    res = registry.execute("no_such_tool", {}, ToolContext())
    assert "未知工具" in res.text


def test_单个collection召回异常被隔离不影响整体():
    # 多库检索：某个 collection 召回抛异常时，该库跳过、不中断，返回其余结果(此处无其余→空)。
    class Boom:
        def search(self, request):
            raise RuntimeError("boom")
    ctx = ToolContext(recaller=Boom(), collections=["c"])
    res = registry.execute("search_knowledge", {"query": "x"}, ctx)
    assert res.hits == []                      # 异常被隔离，无命中
    assert "未在知识库检索到相关内容" in res.text  # 优雅返回，不崩
