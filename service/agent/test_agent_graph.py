"""AgentService 的 LangGraph 循环单测(mock LLM 和 recaller,不连外部服务)。"""

from __future__ import annotations

from recall.schemas import RecallHit, RecallResult
from service.agent.graph import AgentService


class _FakeLLM:
    """按预设脚本依次返回 message(每次 chat 弹一个)。记录每次调用的 tools/tool_choice。"""

    def __init__(self, scripted_messages):
        self._script = list(scripted_messages)
        self.calls = []

    def chat(self, *, messages, tools=None, tool_choice="auto", temperature=0.2):
        self.calls.append({"tools": tools, "tool_choice": tool_choice})
        return self._script.pop(0)


class _FakeRecaller:
    def search(self, request):
        hit = RecallHit(id="1", score=0.9, content="报销先提单", doc_uuid="d1",
                        chunk_index=0, collection="c", breadcrumb="财务 > 报销",
                        filename="财务.md")
        return RecallResult(query=request.query, collection=request.collection,
                            hits=[hit], total=1, latency_ms=1.0,
                            model_dense="d", model_sparse="s")


def _tool_call_msg(name, args_json, call_id="c1"):
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": call_id, "function": {"name": name, "arguments": args_json}}]}


def _text_msg(text):
    return {"role": "assistant", "content": text}


def _svc(llm, max_rounds=4):
    return AgentService(llm_client=llm, recaller=_FakeRecaller(), collections=["c"],
                        top_k=5, max_tool_rounds=max_rounds)


def test_单轮工具调用后作答():
    llm = _FakeLLM([
        _tool_call_msg("search_knowledge", '{"query": "报销流程"}'),
        _text_msg("报销需要先提单再审批。"),
    ])
    ans = _svc(llm).answer("报销怎么弄")
    assert "报销需要先提单" in ans.answer
    assert len(ans.hits) == 1           # 来源被收集
    assert ans.no_answer is False


def test_多轮工具调用循环():
    llm = _FakeLLM([
        _tool_call_msg("get_current_time", "{}", "c1"),
        _tool_call_msg("search_knowledge", '{"query": "本月制度"}', "c2"),
        _text_msg("根据检索，本月制度如下……"),
    ])
    ans = _svc(llm).answer("本月最新制度")
    assert "本月制度" in ans.answer
    # 三次 chat:两次带 tools(auto),最后一次仍 auto(未到上限)
    assert llm.calls[0]["tool_choice"] == "auto"


def test_达到轮数上限末轮禁用工具():
    # max_rounds=1:第 0 轮就是最后一轮,应 tool_choice=none、tools=None
    llm = _FakeLLM([_text_msg("直接作答。")])
    _svc(llm, max_rounds=1).answer("随便问问")
    assert llm.calls[0]["tools"] is None
    assert llm.calls[0]["tool_choice"] == "none"


def test_无检索命中判为no_answer():
    class _EmptyRecaller:
        def search(self, request):
            return RecallResult(query=request.query, collection=request.collection,
                                hits=[], total=0, latency_ms=1.0,
                                model_dense="d", model_sparse="s")
    llm = _FakeLLM([
        _tool_call_msg("search_knowledge", '{"query": "不存在的东西"}'),
        _text_msg("我没检索到相关内容。"),
    ])
    svc = AgentService(llm_client=llm, recaller=_EmptyRecaller(), collections=["c"])
    ans = svc.answer("查个不存在的")
    assert ans.no_answer is True
    assert ans.hits == []


def test_高分命中但LLM说没找到时兜底作答():
    # search 命中 score=0.9(≥0.68 阈值)，但 LLM 最终却说"没找到"——
    # finalize 应否决这个拒答、强制基于高分命中作答(方案 B 安全网)。
    llm = _FakeLLM([
        _tool_call_msg("search_knowledge", '{"query": "报销"}'),
        _text_msg("抱歉，我没有找到相关内容。"),
    ])
    ans = _svc(llm).answer("报销流程")
    assert ans.no_answer is False          # 被高分兜底否决，不拒答
    assert len(ans.hits) == 1              # 高分命中带上来源


def test_闲聊时LLM不调工具直接作答():
    # 无前置意图分类：闲聊由 LLM 自主判断——它不返回 tool_calls，直接给出闲聊回复。
    llm = _FakeLLM([_text_msg("你好，我是企业知识库助手，有什么想查的尽管问～")])
    ans = _svc(llm).answer("你好")
    assert "知识库助手" in ans.answer
    assert ans.hits == []                 # 没调工具，无来源
    assert ans.no_answer is False         # 闲聊回复不是拒答
    # 只调了一次 LLM，且第一次就带着 tools(让它有机会自主决定)
    assert len(llm.calls) == 1
    assert llm.calls[0]["tools"] is not None


def test_参数非法json不崩溃继续():
    llm = _FakeLLM([
        _tool_call_msg("search_knowledge", '{坏的json'),
        _text_msg("已处理。"),
    ])
    ans = _svc(llm).answer("触发坏参数")
    assert ans.answer  # 没崩,拿到了最终文本


def test_知识库不足时降级联网并标注来源(monkeypatch):
    # 知识库召回为空 → LLM 说没找到 → finalize 降级调 web_search → 用联网结果作答、带联网来源。
    import service.agent.tools.registry as reg
    from service.agent.tools.base import ToolResult

    class _EmptyRecaller:
        def search(self, request):
            return RecallResult(query=request.query, collection=request.collection,
                                hits=[], total=0, latency_ms=1.0,
                                model_dense="d", model_sparse="s")

    def fake_execute(name, args, ctx):
        if name == "web_search":
            return ToolResult(text="[联网摘要] RAG 是检索增强生成。",
                              web_sources=[{"title": "RAG 简介", "url": "http://x.com/rag"}])
        # search_knowledge：空召回(知识库无相关内容)
        return ToolResult(text="未在知识库检索到相关内容。")

    monkeypatch.setattr(reg, "execute", fake_execute)

    # 脚本：①调 search_knowledge ②LLM 说没找到 → finalize 触发降级 ③_generate_from_web 再调一次 LLM 生成
    llm = _FakeLLM([
        _tool_call_msg("search_knowledge", '{"query": "什么是RAG"}'),
        _text_msg("知识库里没有找到相关内容。"),
        _text_msg("公司知识库未找到相关内容，以下依据公开资料整理：RAG 是检索增强生成。"),
    ])
    svc = AgentService(llm_client=llm, recaller=_EmptyRecaller(), collections=["c"],
                       enable_web_search=True)
    ans = svc.answer("什么是RAG")
    assert ans.no_answer is False
    assert ans.web_sources and ans.web_sources[0]["url"] == "http://x.com/rag"
    assert "公开资料" in ans.answer


def test_联网开关关闭时知识库不足仍拒答(monkeypatch):
    class _EmptyRecaller:
        def search(self, request):
            return RecallResult(query=request.query, collection=request.collection,
                                hits=[], total=0, latency_ms=1.0,
                                model_dense="d", model_sparse="s")
    llm = _FakeLLM([
        _tool_call_msg("search_knowledge", '{"query": "什么是RAG"}'),
        _text_msg("知识库里没有找到相关内容。"),
    ])
    svc = AgentService(llm_client=llm, recaller=_EmptyRecaller(), collections=["c"],
                       enable_web_search=False)  # 关闭联网
    ans = svc.answer("什么是RAG")
    assert ans.no_answer is True       # 不降级，直接拒答
    assert ans.web_sources == []

