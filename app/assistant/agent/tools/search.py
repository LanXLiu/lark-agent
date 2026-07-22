"""search_knowledge 工具：企业知识库检索(方案 B——纯召回,不跑旧图自评重试)。

由外层 Agent(LLM)自主决定何时调用、query 怎么写、要不要带父子上下文。
include_context 映射 RecallRequest.parent_child,让 LLM 按问题类型选择是否
拉出同父兄弟片段(问"某章节全貌/清单"时开,问精确事实时关,省 token)。
"""

from __future__ import annotations

from typing import Any

from knowledge.retrieval.schemas import RecallHit, RecallRequest
from app.assistant.agent.tools.base import ToolContext, ToolResult
from app.assistant.agent.tools.registry import register_tool
from app.assistant.qa_service import truncate_text

# 单个片段正文的截断长度(与 qa_service.build_user_prompt 一致)
_FRAGMENT_MAX_CHARS = 1800


def _format_hits(hits: list[RecallHit]) -> str:
    """把命中片段拼成给 LLM 的观察文本，每段标注它在文档中的标题路径。"""
    if not hits:
        return "未在知识库检索到相关内容。"
    blocks = []
    for i, hit in enumerate(hits, start=1):
        bc = (getattr(hit, "breadcrumb", "") or "").strip()
        location = bc if bc else (hit.filename or "")
        content = truncate_text(hit.content, _FRAGMENT_MAX_CHARS)
        blocks.append(f"[片段 {i}] {location}\n{content}")
    return "\n\n".join(blocks)


@register_tool
class SearchKnowledgeTool:
    name = "search_knowledge"
    description = (
        "在企业知识库中检索文档片段，回答制度、流程、政策、规范等知识类问题时使用。"
        "若一次检索结果不够或不相关，可换用更精确的关键词再次调用。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "检索查询，尽量完整规范；多轮追问时请补全指代（它/这个/那）后再检索。",
            },
            "include_context": {
                "type": "boolean",
                "description": "是否带出同章节的父子/兄弟片段以补全上下文。问某章节全貌、层级结构、清单类问题时设为 true；问精确单点事实时设为 false。",
                "default": False,
            },
        },
        "required": ["query"],
    }

    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(text="[错误：search_knowledge 需要 query 参数]")
        parent_child = bool(args.get("include_context"))
        # 多库检索：遍历每个 collection 各召回一次，合并后按分数排序取 top_k。
        # 单个 collection 失败不影响其它库（记为空，继续）。
        all_hits: list[RecallHit] = []
        for coll in ctx.collections:
            request = RecallRequest(
                query=query,
                collection=coll,
                top_k=ctx.top_k,
                enable_rerank=ctx.enable_rerank,
                candidate_top_k=ctx.candidate_top_k,
                parent_child=parent_child,
                tenant_id=None,  # 预留：如需按租户隔离，可由 ctx.chat_id 映射后传入
            )
            try:
                result = ctx.recaller.search(request)
                all_hits.extend(result.hits or [])
            except Exception:  # noqa: BLE001 —— 单库失败不影响其它库
                continue
        # 跨库合并后按最终分数(rerank 后)降序，取全局 top_k
        all_hits.sort(key=lambda h: h.score, reverse=True)
        hits = all_hits[: ctx.top_k]
        return ToolResult(text=_format_hits(hits), hits=hits)
