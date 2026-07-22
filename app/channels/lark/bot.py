from __future__ import annotations

import json
import logging
import queue
import re
import sys
import threading
from collections import OrderedDict
from typing import Any

import lark_oapi as lark

from app.channels.lark.lark_config import Settings
from app.channels.lark.lark_config import load_settings
from app.assistant.memory import (
    append_turn,
    configure as configure_memory,
    get_for_answer,
    get_for_rewrite,
    make_key as make_conv_key,
)
from app.assistant.qa_service import format_answer_with_sources
from app.assistant.factory import build_agent_service
from app.channels.lark.feedback import FEEDBACK_ACTION, build_feedback_card, record_feedback
from app.channels.lark.lark_api import LarkApiError
from app.channels.lark.lark_api import add_message_reaction
from app.channels.lark.lark_api import get_bot_open_id
from app.channels.lark.lark_api import get_tenant_access_token
from app.channels.lark.lark_api import reply_card_to_message
from app.channels.lark.lark_api import send_text_message_to_chat
from app.assistant.llm_client import BailianChatClient
from app.channels.lark.observability import QaTrace
from app.channels.lark.relay import build_relay_payload, post_to_enterprise_server
from app.channels.lark.source_names import SourceNameResolver

LOGGER = logging.getLogger(__name__)

_PROCESSED_MAX = 1000
_processed_message_ids: OrderedDict[str, None] = OrderedDict()
_processed_lock = threading.Lock()

# 并发兜底：有界队列 + 固定 worker 线程池（削峰）。
#
# 为什么不用无界队列/ThreadPoolExecutor 的默认无界队列：洪峰时无界队列会一直
# 吞入请求，内存无上限、排队时间无上限，最终 OOM 拖垮整个进程——所有人一起失败。
# 有界队列在满时「优雅拒绝」新请求（回一句稍后再试），用少数人的快速失败换取
# 整个系统始终稳定、多数人正常。worker 数决定「最多几路并发打百炼」。
#
# 这些对象在 start_workers() 里按配置初始化；单例 AgentService（LangGraph 编排的
# Function Calling 服务）也在那时建一次，之后所有 worker 线程共用
# （answer 无共享可变状态，跨线程安全）。
_work_queue: queue.Queue[tuple[dict[str, Any], str | None, Settings]] | None = None
_reject_executor_lock = threading.Lock()
_qa_service: Any = None
_qa_service_lock = threading.Lock()


def already_processed(message_id: str | None) -> bool:
    """Return True if this message_id was handled before; otherwise record it.

    Lark redelivers the same event when our handler does not ack in time, which
    made the bot answer the same question several times.
    """
    if not message_id:
        return False
    with _processed_lock:
        if message_id in _processed_message_ids:
            return True
        _processed_message_ids[message_id] = None
        while len(_processed_message_ids) > _PROCESSED_MAX:
            _processed_message_ids.popitem(last=False)
        return False


def get_qa_service(settings: Settings):
    """进程内单例 Agent 问答服务，所有 worker 线程共用。

    AgentService：LangGraph 编排 Function Calling，LLM 自主调用检索等工具。
    answer 无共享可变状态(请求数据都在局部 state)，故可安全跨线程共用。
    """
    global _qa_service
    if _qa_service is not None:
        return _qa_service
    with _qa_service_lock:
        if _qa_service is None:
            _qa_service = build_agent_service(settings)
            LOGGER.info("问答服务：Agent 工具调用模式(LangGraph FC，工具轮上限=%d)",
                        settings.rag_max_tool_rounds)
        return _qa_service


def start_workers(settings: Settings) -> None:
    """按配置建有界队列 + 固定 worker 线程。启动时调用一次。"""
    global _work_queue
    _work_queue = queue.Queue(maxsize=settings.rag_queue_maxsize)

    def _worker_loop() -> None:
        while True:
            payload, message_id, item_settings = _work_queue.get()
            try:
                _process_message(payload, message_id, item_settings)
            except Exception:  # noqa: BLE001 —— 单条失败不能杀死 worker 线程
                LOGGER.exception("Worker failed: message_id=%s", message_id)
            finally:
                _work_queue.task_done()

    for index in range(settings.rag_worker_count):
        thread = threading.Thread(
            target=_worker_loop,
            name=f"lark-worker-{index}",
            daemon=True,
        )
        thread.start()
    LOGGER.info(
        "并发兜底就绪：worker=%d，队列上限=%d",
        settings.rag_worker_count,
        settings.rag_queue_maxsize,
    )


def handle_message_event(data: lark.im.v1.P2ImMessageReceiveV1, settings: Settings) -> None:
    """Lark websocket callback. Dedupe, ack fast, enqueue for background workers."""
    event = typed_event_to_dict(data)
    payload = build_relay_payload(event)
    message_id = payload["message"].get("message_id")

    if already_processed(message_id):
        LOGGER.info("Duplicate event ignored: message_id=%s", message_id)
        return

    if _work_queue is None:
        LOGGER.error("Work queue not initialized; dropping message_id=%s", message_id)
        return

    try:
        _work_queue.put_nowait((payload, message_id, settings))
    except queue.Full:
        # 队列已满：优雅拒绝，让用户知道「量大稍后再试」，而不是静默丢弃或拖垮系统。
        LOGGER.warning(
            "队列已满(%d)，拒绝新请求：message_id=%s",
            settings.rag_queue_maxsize,
            message_id,
        )
        _reject_busy(payload, settings)


def _process_message(payload: dict[str, Any], message_id: str | None, settings: Settings) -> None:
    try:
        qa_question = extract_qa_question(payload, settings)
        if qa_question is not None:
            handle_rag_question(payload, qa_question, settings)
            return

        if not settings.enterprise_server_url:
            print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stdout, flush=True)
            LOGGER.info(
                "No enterprise server configured; message printed: message_id=%s chat_type=%s",
                message_id,
                payload.get("chat_type"),
            )
            return

        post_to_enterprise_server(
            settings.enterprise_server_url,
            payload,
            token=settings.enterprise_server_token,
            timeout_seconds=settings.forward_timeout_seconds,
        )
        LOGGER.info("Message relayed: message_id=%s chat_type=%s", message_id, payload.get("chat_type"))
    except Exception:
        LOGGER.exception("Message handling failed: message_id=%s", message_id)


def _reject_busy(payload: dict[str, Any], settings: Settings) -> None:
    """队列满时的优雅拒绝：只对「@机器人的提问」回一句稍后再试。

    在独立短线程里发送，避免阻塞 websocket 回调（回调必须尽快返回，否则飞书重投）。
    只对 RAG 提问回复——转发类消息被拒绝时无需打扰用户。
    """
    question = extract_qa_question(payload, settings)
    if question is None:
        return  # 非提问（转发/闲聊）被拒时不回，避免噪音
    chat_id = payload["message"].get("chat_id")
    chat_type = payload["message"].get("chat_type")
    message_id = payload["message"].get("message_id")
    if not chat_id:
        return

    def _send() -> None:
        try:
            tenant_token = get_tenant_access_token(
                settings.lark_open_api_base_url,
                settings.lark_app_id,
                settings.lark_app_secret,
                timeout_seconds=settings.forward_timeout_seconds,
            )
            send_text_message_to_chat(
                settings.lark_open_api_base_url,
                tenant_token,
                chat_id,
                "当前咨询量较大，我这会儿有点忙不过来，请稍等片刻再 @我 提问～",
                timeout_seconds=settings.forward_timeout_seconds,
                reply_to_message_id=message_id,
            )
        except Exception:  # noqa: BLE001 —— 拒绝提示发送失败仅记日志
            LOGGER.warning("发送「繁忙」提示失败: message_id=%s", message_id)

    with _reject_executor_lock:
        threading.Thread(target=_send, name="lark-reject", daemon=True).start()


def handle_rag_question(
    payload: dict[str, Any],
    question: str,
    settings: Settings,
) -> None:
    chat_id = payload["message"].get("chat_id")
    message_id = payload["message"].get("message_id")
    user_open_id = (payload.get("sender") or {}).get("open_id")
    trace = QaTrace(chat_id, user_open_id, question)

    if not chat_id:
        LOGGER.warning("RAG question skipped because chat_id is missing: message_id=%s", message_id)
        trace.set_stage("no_chat_id")
        trace.finish()
        return

    try:
        tenant_token = get_tenant_access_token(
            settings.lark_open_api_base_url,
            settings.lark_app_id,
            settings.lark_app_secret,
            timeout_seconds=settings.forward_timeout_seconds,
        )
    except LarkApiError as exc:
        LOGGER.exception("RAG answer skipped because tenant_access_token failed")
        trace.set_stage("token_fail")
        trace.set_error(str(exc))
        trace.finish()
        return

    # 快速反馈「已收到」：在用户原消息上贴一个 OK 表情。
    # 失败不影响后续问答（权限不足等），仅记日志。
    if message_id:
        try:
            add_message_reaction(
                settings.lark_open_api_base_url,
                tenant_token,
                message_id,
                "OK",
                timeout_seconds=settings.forward_timeout_seconds,
            )
        except Exception:  # noqa: BLE001 —— 表情回应失败不能影响问答
            LOGGER.warning("贴「已收到」表情失败（忽略）: message_id=%s", message_id)

    if not question.strip():
        send_text_message_to_chat(
            settings.lark_open_api_base_url,
            tenant_token,
            chat_id,
            "请在 @机器人 后面输入要查询的问题。",
            timeout_seconds=settings.forward_timeout_seconds,
        )
        trace.set_stage("empty_question")
        trace.finish()
        return

    if not settings.bailian_api_key:
        send_text_message_to_chat(
            settings.lark_open_api_base_url,
            tenant_token,
            chat_id,
            "RAG 问答还没有配置 BAILIAN_API_KEY，暂时不能调用大模型。",
            timeout_seconds=settings.forward_timeout_seconds,
        )
        trace.set_stage("no_api_key")
        trace.finish()
        return

    answer_text = ""
    has_answer = False  # 仅「成功有答案」时发带反馈按钮的卡片
    conv_key = make_conv_key(chat_id, user_open_id)
    # 多轮：改写用短历史（近几轮），生成用长历史（摘要 + 预算内全文）。均按 key 外部存、
    # 随参数传入，故 QaService 可安全共享单例。
    rewrite_history = get_for_rewrite(conv_key)
    answer_context = get_for_answer(conv_key)
    try:
        qa_service = get_qa_service(settings)  # 进程内单例，所有 worker 线程共用
        result = qa_service.answer(
            question.strip(),
            rewrite_history=rewrite_history,
            answer_context=answer_context,
            user_open_id=user_open_id,
            chat_id=chat_id,
            chat_type=chat_type,
        )

        # 意图分类判为闲聊/问机器人自身：回一句话术，不带来源、不入多轮记忆（图内已跳过召回/生成）
        if getattr(result, "is_chitchat", False):
            send_text_message_to_chat(
                settings.lark_open_api_base_url,
                tenant_token,
                chat_id,
                result.answer,
                timeout_seconds=settings.forward_timeout_seconds,
                reply_to_message_id=message_id,
            )
            trace.set_stage("chitchat")
            trace.finish()
            LOGGER.info("闲聊拦截（图 route 节点）：message_id=%s", message_id)
            return

        resolver = SourceNameResolver(
            settings.lark_open_api_base_url,
            tenant_token,
            timeout_seconds=settings.bailian_timeout_seconds,
        )
        answer_text = format_answer_with_sources(result, resolver)

        # 记录改写前后（供观测改写效果）
        if result.rewritten_question is not None:
            trace.set_rewrite(
                question.strip(), result.rewritten_question, result.rewrite_ms
            )

        if not result.hits and not getattr(result, "web_sources", None):
            # 召回为空，或召回到片段但 LLM 判定无法回答（no_answer）——都视为「没有有效答案」，不带来源
            if getattr(result, "no_answer", False):
                trace.set_stage("no_answer")  # 召回到了但内容不相关，LLM 拒答
                trace.mark_recall(
                    hit_count=0,
                    top_score=result.recall_top_score,
                    sources=[],
                    recall_ms=result.recall_ms,
                )
            else:
                trace.set_stage("recall_empty")  # 召回本身为空
                trace.mark_recall(
                    hit_count=0, top_score=None, sources=[], recall_ms=result.recall_ms
                )
        else:
            has_answer = True
            web_sources = getattr(result, "web_sources", None) or []
            if web_sources:
                # 降级联网：有效答案(来源=联网)，走成功分支——带卡片、入多轮记忆
                trace.set_stage("web_search")
                trace.mark_recall(
                    hit_count=0,
                    top_score=result.recall_top_score,
                    sources=[s.get("url", "") for s in web_sources],
                    recall_ms=result.recall_ms,
                )
            else:
                trace.set_stage("success")
                sources = _resolve_source_labels(result, resolver)
                trace.mark_recall(
                    hit_count=len(result.hits),
                    top_score=result.recall_top_score,
                    sources=sources,
                    recall_ms=result.recall_ms,
                )
            trace.mark_llm(answer_chars=len(result.answer or ""), llm_ms=result.llm_ms)
            # 多轮：仅成功有答案时存这一轮（存原始问题 + 答案），避免污染上下文
            append_turn(conv_key, question.strip(), result.answer)
    except Exception as exc:
        LOGGER.exception("RAG answer failed: message_id=%s", message_id)
        # 召回连不上（重试多次仍失败）给更明确的文案；其余统一兜底
        if "RAG recall failed" in str(exc):
            answer_text = "知识库暂时连不上，已重试多次仍未成功，请稍后再试。"
        else:
            answer_text = "知识库问答暂时失败了，请稍后再试；详细错误已写入服务日志。"
        trace.set_stage("rag_fail")
        trace.set_error(str(exc))

    # 成功有答案：发带 👍/👎 反馈按钮的卡片；其余情况发纯文本
    sent_as_card = False
    if has_answer and message_id:
        try:
            card = build_feedback_card(answer_text, trace.trace_id, user_open_id)
            reply_card_to_message(
                settings.lark_open_api_base_url,
                tenant_token,
                message_id,
                card,
                timeout_seconds=settings.forward_timeout_seconds,
            )
            sent_as_card = True
        except Exception:  # noqa: BLE001 —— 卡片失败则退回纯文本，保证用户收到答案
            LOGGER.warning("发送反馈卡片失败，退回纯文本: message_id=%s", message_id)

    if not sent_as_card:
        send_text_message_to_chat(
            settings.lark_open_api_base_url,
            tenant_token,
            chat_id,
            answer_text,
            timeout_seconds=settings.forward_timeout_seconds,
            reply_to_message_id=message_id,
        )
    LOGGER.info("RAG answer sent: message_id=%s chat_id=%s", message_id, chat_id)
    trace.finish()


def _resolve_source_labels(result, resolver) -> list[str]:
    """复用 SourceNameResolver 把命中翻译成「群名/文档名」并去重，仅用于日志。"""
    seen: set[str] = set()
    labels: list[str] = []
    for hit in result.hits:
        try:
            label = resolver.label_for(hit)
        except Exception:  # noqa: BLE001 —— 翻译失败不影响日志记录
            label = hit.filename or hit.doc_uuid or "未知来源"
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def extract_qa_question(payload: dict[str, Any], settings: Settings) -> str | None:
    message = payload.get("message") or {}
    chat_type = message.get("chat_type")
    if message.get("message_type") != "text":
        return None

    content = message.get("content") or {}
    text = content.get("text") if isinstance(content, dict) else ""

    # 私聊(p2p)：一对一场景，直接把整条文本当问题，无需 @机器人。
    if chat_type == "p2p":
        cleaned = (text or "").strip()
        return cleaned or None

    # 群聊(group)：必须 @机器人才触发，避免群里每句话都问答。
    if chat_type != "group":
        return None
    mentions = collect_mentions(payload.get("raw_event") or {})
    if not mentions:
        return None
    if not mentions_bot(mentions, settings):
        return None
    return clean_question_text(text or "", mentions)


def mentions_bot(mentions: list[dict[str, Any]], settings: Settings) -> bool:
    bot_open_id = settings.lark_bot_open_id
    if not bot_open_id:
        try:
            tenant_token = get_tenant_access_token(
                settings.lark_open_api_base_url,
                settings.lark_app_id,
                settings.lark_app_secret,
                timeout_seconds=settings.forward_timeout_seconds,
            )
            bot_open_id = get_bot_open_id(
                settings.lark_open_api_base_url,
                tenant_token,
                timeout_seconds=settings.forward_timeout_seconds,
            )
        except LarkApiError:
            LOGGER.exception("Could not resolve bot open_id; falling back to any mention")
            return True

    if not bot_open_id:
        LOGGER.warning("Bot open_id is empty; falling back to any mention")
        return True

    return any(extract_mention_open_id(mention) == bot_open_id for mention in mentions)


def collect_mentions(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "mentions" and isinstance(item, list):
                found.extend(mention for mention in item if isinstance(mention, dict))
            else:
                found.extend(collect_mentions(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(collect_mentions(item))
    return found


def extract_mention_open_id(mention: dict[str, Any]) -> str | None:
    mention_id = mention.get("id") or {}
    if isinstance(mention_id, dict):
        return mention_id.get("open_id")
    return mention.get("open_id")


def clean_question_text(text: str, mentions: list[dict[str, Any]]) -> str:
    cleaned = text
    for mention in mentions:
        key = mention.get("key")
        if key:
            cleaned = cleaned.replace(str(key), "")
        name = mention.get("name")
        if name:
            cleaned = cleaned.replace(f"@{name}", "")

    cleaned = re.sub(r"<at[^>]*>.*?</at>", "", cleaned)
    cleaned = re.sub(r"^\s*@\S+\s*", "", cleaned)
    return cleaned.strip()


def typed_event_to_dict(data: Any) -> dict[str, Any]:
    marshaled = lark.JSON.marshal(data)
    envelope = json.loads(marshaled)
    return envelope.get("event") or envelope


def build_event_handler(settings: Settings) -> lark.EventDispatcherHandler:
    def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
        handle_message_event(data, settings)

    def on_card_action(data):
        return handle_card_action(data)

    return (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )


def handle_card_action(data):
    """处理卡片按钮点击（👍/👎 反馈）。

    群聊共享卡片：按钮不替换、不消失，谁都能点；仅给点击者弹 toast。
    反馈按 (trace_id, user_open_id) 记录，is_asker 标注点击者是否为提问者。
    全程容错，失败也返回一个安全 toast。
    """
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        CallBackToast,
        P2CardActionTriggerResponse,
    )

    def _toast(content: str, toast_type: str = "info"):
        resp = P2CardActionTriggerResponse()
        resp.toast = CallBackToast()
        resp.toast.type = toast_type
        resp.toast.content = content
        return resp

    try:
        event = getattr(data, "event", None)
        action = getattr(event, "action", None)
        value = getattr(action, "value", None) or {}
        if value.get("action") != FEEDBACK_ACTION:
            return _toast("")  # 非反馈按钮，忽略

        vote = value.get("vote")
        trace_id = value.get("trace_id") or ""
        asker = value.get("asker") or ""
        operator = getattr(event, "operator", None)
        user_open_id = getattr(operator, "open_id", None)
        is_asker = bool(user_open_id) and user_open_id == asker

        record_feedback(trace_id, vote, user_open_id, is_asker)
        return _toast("感谢反馈！", "success")
    except Exception:  # noqa: BLE001 —— 回调失败不能抛
        LOGGER.exception("处理卡片反馈失败")
        return _toast("反馈处理出错了，请稍后再试", "error")


def _configure_memory(settings: Settings) -> None:
    """按配置初始化对话记忆；有 key 时注入摘要用 LLM（复用问答同款客户端）。"""
    summarizer = None
    if settings.bailian_api_key:
        summarizer = BailianChatClient(
            api_key=settings.bailian_api_key,
            base_url=settings.bailian_base_url,
            model=settings.bailian_model,
            timeout_seconds=settings.bailian_timeout_seconds,
        )
    configure_memory(
        rewrite_turns=settings.memory_rewrite_turns,
        summary_enabled=settings.memory_summary_enabled,
        summary_trigger_tokens=settings.memory_summary_trigger_tokens,
        summary_max_tokens=settings.memory_summary_max_tokens,
        ttl_seconds=settings.memory_ttl_seconds,
        max_sessions=settings.memory_max_sessions,
        summarizer=summarizer,
        persist_path=settings.memory_persist_path,
    )
    LOGGER.info(
        "对话记忆就绪：摘要触发=%d token，改写用%d轮，摘要=%s，持久化=%s",
        settings.memory_summary_trigger_tokens,
        settings.memory_rewrite_turns,
        "开" if (settings.memory_summary_enabled and summarizer) else "关",
        settings.memory_persist_path or "关(纯内存)",
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    settings = load_settings(require_enterprise_server=False)
    _configure_memory(settings)  # 配置对话记忆（token 预算窗口 + 摘要），注入摘要用 LLM
    start_workers(settings)  # 启动有界队列 + 固定 worker 线程（并发兜底）
    if settings.bailian_api_key:
        get_qa_service(settings)  # 预热单例，避免第一个用户承担初始化开销
    event_handler = build_event_handler(settings)
    client = lark.ws.Client(
        settings.lark_app_id,
        settings.lark_app_secret,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    if settings.enterprise_server_url:
        LOGGER.info("Lark long connection starting; messages will be relayed")
    else:
        LOGGER.info("Lark long connection starting; messages will be printed when not handled by RAG")
    client.start()


if __name__ == "__main__":
    main()
