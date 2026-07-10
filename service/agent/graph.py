"""Agent 编排(LangGraph StateGraph 编排 Function Calling 工具调用循环)。

    START → intent ──(闲聊)──────────────────→ END(回话术)
              │(知识问题)
              ▼
           agent ◀───────────────────┐
              │                       │
              ├─(有 tool_calls & 未到上限)→ execute ┘   (条件边循环)
              │
              └─(无 tool_calls / 到上限)→ finalize → END

- intent：便宜小模型意图分类，闲聊/问机器人自身直接回话术、不进循环；
- agent：调 LLM(带 tools)，让它自主决定调哪个工具、调几次、要不要换 query 再搜；
- execute：执行工具(检索等)，结果回传，hits 累积；
- finalize：组装 QaAnswer(去重 hits、拒答判定)，字段与旧直线版一致。

对话记忆直接作为 messages 传入(不再单独 rewrite——LLM 看历史自行改写)。
检索工具内部纯召回(方案 B)，"够不够/要不要再搜"由本层 LLM 判断。
"""

from __future__ import annotations

import json
import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from loguru import logger

from prompts.agent import AGENT_SYSTEM_PROMPT, build_web_fallback_user, WEB_FALLBACK_SYSTEM_PROMPT
from recall.schemas import RecallHit
from service.agent.tools.base import ToolContext
from service.agent.tools import registry
from service.llm_client import BailianChatClient
from service.memory import AnswerContext
from service.qa_service import NO_RECALL_REPLY, QaAnswer, _is_no_answer

DEFAULT_MAX_TOOL_ROUNDS = 4


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    all_hits: list[RecallHit]
    round: int
    searched: bool
    final_answer: str
    web_sources: list[dict[str, str]]
    llm_ms: float


def _strip_reasoning(msg: dict[str, Any]) -> dict[str, Any]:
    """append 回 messages 前剥掉 reasoning_content(思考模式下回传会被网关拒)。"""
    return {k: v for k, v in msg.items() if k != "reasoning_content"}


def _history_to_messages(context: AnswerContext | None) -> list[dict[str, Any]]:
    """把对话记忆(摘要 + 最近轮)转成给 Agent 的历史 messages。"""
    if context is None or context.is_empty():
        return []
    msgs: list[dict[str, Any]] = []
    if context.summary:
        msgs.append({"role": "system", "content": f"【前情摘要】{context.summary}"})
    for q, a in context.recent_turns:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": a})
    return msgs


def _dedup_hits(hits: list[RecallHit]) -> list[RecallHit]:
    seen: set[tuple[str, int]] = set()
    out: list[RecallHit] = []
    for h in hits:
        key = (h.doc_uuid, h.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def _last_user_question(messages: list[dict[str, Any]]) -> str:
    """从 messages 里取最后一条 user 内容(降级联网时作为搜索 query)。"""
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            return str(m["content"]).strip()
    return ""


class AgentService:
    """LangGraph 编排的 Agent 问答服务。对外 answer() 返回 QaAnswer(与旧版兼容)。"""

    def __init__(
        self,
        *,
        llm_client: BailianChatClient,
        recaller: Any,
        collections: list[str] | str,
        top_k: int = 5,
        enable_rerank: bool | None = None,
        candidate_top_k: int | None = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
        recall_quality_min: float = 0.68,
        enable_web_search: bool = True,
    ) -> None:
        self.llm = llm_client
        self.recaller = recaller
        # 支持单个(str)或多个(list) collection——多库检索合并结果
        self.collections = [collections] if isinstance(collections, str) else list(collections)
        self.top_k = top_k
        self.enable_rerank = enable_rerank
        self.candidate_top_k = candidate_top_k
        self.max_tool_rounds = max(1, max_tool_rounds)
        self.recall_quality_min = recall_quality_min
        self.enable_web_search = enable_web_search
        self._tool_schemas = registry.tool_schemas()
        self._graph = self._build_graph()

    # ---- 节点 ----

    def _node_agent(self, state: AgentState) -> dict[str, Any]:
        rnd = state.get("round", 0)
        last = rnd >= self.max_tool_rounds - 1
        t0 = time.perf_counter()
        msg = self.llm.chat(
            messages=state["messages"],
            tools=None if last else self._tool_schemas,
            tool_choice="none" if last else "auto",
        )
        llm_ms = (state.get("llm_ms") or 0.0) + (time.perf_counter() - t0) * 1000.0
        new_messages = state["messages"] + [_strip_reasoning(msg)]
        return {"messages": new_messages, "round": rnd + 1, "llm_ms": llm_ms}

    def _node_execute(self, state: AgentState) -> dict[str, Any]:
        msg = state["messages"][-1]  # agent 节点刚 append 的 assistant message
        ctx = ToolContext(
            recaller=self.recaller,
            collections=self.collections,
            top_k=self.top_k,
            enable_rerank=self.enable_rerank,
            candidate_top_k=self.candidate_top_k,
        )
        rnd = state.get("round", 0)
        messages = list(state["messages"])
        all_hits = list(state.get("all_hits") or [])
        searched = state.get("searched", False)
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args or "{}")
            except (json.JSONDecodeError, TypeError):
                logger.warning("[Agent] 第{}轮 工具 {} 参数非法JSON：{}", rnd, name, raw_args)
                messages.append({"role": "tool", "tool_call_id": call.get("id"),
                                 "content": f"[参数解析失败，请修正后重试：{raw_args}]"})
                continue
            logger.info("[Agent] 第{}轮 调用工具 {} 参数={}", rnd, name, args)
            res = registry.execute(name, args, ctx)
            logger.info("[Agent] 第{}轮 工具 {} 返回 {} 条命中", rnd, name, len(res.hits))
            if name == "search_knowledge":
                searched = True  # 标记本次会话确实检索过知识库(用于区分闲聊 vs 拒答)
            all_hits.extend(res.hits)
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "content": res.text})
        return {"messages": messages, "all_hits": all_hits, "searched": searched}

    def _node_finalize(self, state: AgentState) -> dict[str, Any]:
        # 取最后一条 assistant 文本
        text = ""
        for m in reversed(state["messages"]):
            if m.get("role") == "assistant" and m.get("content"):
                text = str(m["content"]).strip()
                break
        hits = _dedup_hits(state.get("all_hits") or [])
        searched = state.get("searched", False)
        # 未检索(闲聊/打招呼/常识类，LLM 没调 search_knowledge)：直接用 LLM 的回复，
        # 不走拒答逻辑(否则"没 hits"会被误判成拒答)。
        if not searched:
            logger.info("[Agent] 结束：未检索(闲聊/直接作答)，共 {} 轮", state.get("round", 0))
            return {"final_answer": text or NO_RECALL_REPLY}
        # 检索过的知识类问题才做拒答判定 + 高分兜底(方案 B)：把"够不够"主要交给 LLM，
        # 但加一道安全网——只要召回里有足够高分(≥ recall_quality_min)的命中，就认为知识库
        # 确有相关内容，不因 LLM 一时"完美主义"说没找到而拒答(避免"搜到 0.86 高分却拒答")。
        top_score = max((h.score for h in hits), default=0.0)
        has_good = bool(hits) and top_score >= self.recall_quality_min
        no_ans = (not hits) or (_is_no_answer(text) and not has_good)

        # 降级联网(方案 B)：知识库召回不足(判定拒答)且开关开启时，不直接拒答，
        # 转而联网补充。web_search 是内部工具(不给 LLM 平级选)，此处由代码主动降级调用。
        if no_ans and self.enable_web_search:
            question = _last_user_question(state["messages"])
            web = registry.execute("web_search", {"query": question}, ToolContext())
            if web.web_sources:  # 联网确有结果
                web_answer = self._generate_from_web(question, web.text)
                logger.info(
                    "[Agent] 结束：知识库不足(top={:.3f})→降级联网，命中 {} 源",
                    top_score, len(web.web_sources),
                )
                return {
                    "final_answer": web_answer,
                    "web_sources": web.web_sources,
                }
            logger.info("[Agent] 结束：知识库不足且联网无结果/不可用，拒答")

        logger.info(
            "[Agent] 结束：共 {} 轮，累计命中 {} 条(top={:.3f})，判定={}",
            state.get("round", 0), len(hits), top_score, "拒答" if no_ans else "作答",
        )
        return {"final_answer": (NO_RECALL_REPLY if no_ans else text)}

    def _generate_from_web(self, question: str, web_text: str) -> str:
        """基于联网结果生成答案。措辞上明确「公司知识库未找到、以下据公开资料」，
        划清「非公司内部规定」的边界，避免联网结果冒充公司知识。"""
        system = WEB_FALLBACK_SYSTEM_PROMPT
        user = build_web_fallback_user(question, web_text)
        try:
            msg = self.llm.chat(messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ])
            return (msg.get("content") or "").strip() or NO_RECALL_REPLY
        except Exception:  # noqa: BLE001 —— 生成失败回退为拒答
            return NO_RECALL_REPLY

    # ---- 条件边 ----

    def _after_agent(self, state: AgentState) -> str:
        msg = state["messages"][-1]  # agent 刚 append 的 assistant message
        has_calls = bool(msg.get("tool_calls"))
        # 到上限时(agent 节点已用 tool_choice=none)不会再有 tool_calls，直接 finalize
        if has_calls and state.get("round", 0) < self.max_tool_rounds:
            return "execute"
        return "finalize"

    # ---- 组图 ----

    def _build_graph(self):
        g = StateGraph(AgentState)
        g.add_node("agent", self._node_agent)
        g.add_node("execute", self._node_execute)
        g.add_node("finalize", self._node_finalize)

        # 无前置意图分类：闲聊/是否调工具由 agent(LLM)通过 Function Calling 自主判断。
        g.add_edge(START, "agent")
        g.add_conditional_edges(
            "agent", self._after_agent, {"execute": "execute", "finalize": "finalize"}
        )
        g.add_edge("execute", "agent")
        g.add_edge("finalize", END)
        return g.compile()

    # ---- 对外接口 ----

    def answer(
        self,
        question: str,
        rewrite_history: list[tuple[str, str]] | None = None,
        answer_context: AnswerContext | None = None,
        *,
        user_open_id: str | None = None,
        chat_id: str | None = None,
    ) -> QaAnswer:
        """对外问答入口，返回 QaAnswer。

        rewrite_history 保留在签名里(向后兼容)但本层不用——多轮改写交由 LLM 看历史自行完成。
        """
        messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
        messages += _history_to_messages(answer_context)
        messages.append({"role": "user", "content": question})

        init: AgentState = {"messages": messages, "all_hits": [], "round": 0}
        final: AgentState = self._graph.invoke(init)

        # 无前置意图分类：闲聊也走 agent 流程——LLM 不调工具、直接给出闲聊回复，
        # 此时 all_hits 为空、answer_text 非兜底文案，no_ans=False，正常返回(不带来源)。
        hits = _dedup_hits(final.get("all_hits") or [])
        web_sources = final.get("web_sources") or []
        answer_text = final.get("final_answer", NO_RECALL_REPLY)
        no_ans = answer_text == NO_RECALL_REPLY
        return QaAnswer(
            answer=answer_text,
            # 降级联网时用 web_sources 标来源、知识库 hits 清空；否则用知识库 hits。
            hits=[] if (no_ans or web_sources) else hits,
            web_sources=web_sources,
            llm_ms=final.get("llm_ms"),
            no_answer=no_ans,
            is_chitchat=False,
        )
