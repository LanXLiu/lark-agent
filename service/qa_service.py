"""RAG 问答的可复用工具（service 层）。

数据结构与纯函数，供 Agent 编排（service/agent）复用：
- QaAnswer：对外统一返回结构（channel / 评测都依赖它的字段）
- build_user_prompt：把检索片段 + 对话上下文拼成生成 prompt
- format_answer_with_sources：答案 + 带小标题的引用来源（知识库 / 联网）
- NO_ANSWER_MARK / NO_RECALL_REPLY：无关拒答标记与兜底话术
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prompts.qa import QA_ANSWER_REQUIREMENTS, QA_USER_PROMPT_HEADER
from recall.schemas import RecallHit
from service.memory import AnswerContext

# LLM 判定「检索片段无法回答问题」时输出的标记
NO_ANSWER_MARK = "[NO_ANSWER]"
# 召回为空 / LLM 拒答时对用户的兜底话术
NO_RECALL_REPLY = "我没有在知识库里检索到相关内容。"


def _is_no_answer(answer: str | None) -> bool:
    text = (answer or "").strip()
    if not text:
        return True
    return NO_ANSWER_MARK in text


@dataclass(frozen=True)
class QaAnswer:
    answer: str
    hits: list[RecallHit]
    recall_ms: float | None = None
    llm_ms: float | None = None
    recall_top_score: float | None = None
    rewritten_question: str | None = None
    rewrite_ms: float | None = None
    is_followup: bool = False
    no_answer: bool = False
    is_chitchat: bool = False  # 意图分类判为闲聊/问机器人自身：answer 为话术，不召回不生成
    # 降级联网搜索的来源(title/url)；知识库召回不足时启用，答案标注「来源：联网搜索」
    web_sources: list[dict[str, str]] = field(default_factory=list)


def build_user_prompt(
    question: str,
    hits: list[RecallHit],
    context: AnswerContext | None = None,
) -> str:
    context_blocks = []
    for index, hit in enumerate(hits, start=1):
        bc = (getattr(hit, "breadcrumb", "") or "").strip()
        location = bc if bc else (hit.filename or "")
        content = truncate_text(hit.content, 1800)
        context_blocks.append(f"[片段 {index}] {location}\n{content}")

    history_section = ""
    if context is not None and not context.is_empty():
        parts: list[str] = []
        if context.summary:
            parts.append(f"【前情摘要】\n{context.summary}")
        if context.recent_turns:
            recent = "\n".join(
                f"用户：{q}\n助手：{a}" for q, a in context.recent_turns
            )
            parts.append(f"【最近对话】\n{recent}")
        history_section = "对话历史（供理解上下文）：\n" + "\n\n".join(parts) + "\n\n"

    return (
        QA_USER_PROMPT_HEADER
        + history_section
        + f"用户问题：{question}\n\n"
        "知识库片段（每段开头是它在文档中的标题路径）：\n"
        + "\n\n".join(context_blocks)
        + QA_ANSWER_REQUIREMENTS
    )


def _leaf_section(breadcrumb: str) -> str:
    """从 "A > B > C" 的标题路径里取末级小标题；顶层文档（路径只有一段）不算定位。"""
    parts = [p.strip() for p in (breadcrumb or "").split(">") if p.strip()]
    return parts[-1] if len(parts) >= 2 else ""


def format_answer_with_sources(result: QaAnswer, resolver=None, max_sources: int = 3) -> str:
    if not result.hits:
        # 降级联网：无知识库来源，但有联网来源时标注「来源：联网搜索」
        web = getattr(result, "web_sources", None) or []
        if web:
            lines = [result.answer.strip(), "", "来源：联网搜索"]
            seen_urls: set[str] = set()
            idx = 0
            for src in web:
                title = (src.get("title") or "").strip()
                url = (src.get("url") or "").strip()
                if not (title or url) or url in seen_urls:
                    continue
                seen_urls.add(url)
                idx += 1
                lines.append(f"{idx}. {title} {url}".strip())
                if idx >= max_sources:
                    break
            return "\n".join(lines)
        return result.answer
    seen: set[str] = set()
    labels: list[str] = []
    for hit in result.hits:
        doc = (
            resolver.label_for(hit)
            if resolver is not None
            else (hit.filename or hit.doc_uuid or "未知来源")
        )
        section = _leaf_section(getattr(hit, "breadcrumb", ""))
        # 文档名 › 末级小标题（有小标题才拼），一行内定位又不臃肿
        label = f"{doc} › {section}" if section else doc
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
        if len(labels) >= max_sources:
            break
    lines = [result.answer.strip(), "", "引用来源："]
    for index, label in enumerate(labels, start=1):
        lines.append(f"{index}. {label}")
    return "\n".join(lines)


def truncate_text(text: str, limit: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n...[已截断]"
