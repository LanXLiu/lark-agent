"""把召回片段里的飞书 ID/路径翻译成「群名 / 文档名」，带内存缓存。

召回结果只带飞书内部 ID（chat_id、wiki token），不含中文名。这里实时调
飞书 API 翻译，并缓存结果——同一个群/文档只查一次，之后命中缓存，几乎无延迟。
"""

from __future__ import annotations

import re
import threading

from channels.lark.lark_api import LarkApiError, get_chat_name, get_wiki_node_title
from recall.schemas import RecallHit

# chat_id 形如 oc_xxxxxxxx；wiki token 形如 wiki_<token> 出现在文件名/路径里
_CHAT_ID_RE = re.compile(r"oc_[0-9a-f]+")
_WIKI_TOKEN_RE = re.compile(r"wiki_([0-9A-Za-z]+)")


class SourceNameResolver:
    """把 RecallHit 解析为「群名 / 文档名」，结果按 id 缓存。

    缓存是进程级共享的（类变量），跨多次提问命中——群名/文档名只查一次 API。
    """

    _chat_cache: dict[str, str | None] = {}
    _doc_cache: dict[str, str | None] = {}
    _lock = threading.Lock()

    def __init__(self, base_url: str, tenant_access_token: str, *, timeout_seconds: float = 5) -> None:
        self.base_url = base_url
        self.token = tenant_access_token
        self.timeout_seconds = timeout_seconds

    def label_for(self, hit: RecallHit) -> str:
        """返回「群名 / 文档名」；任一拿不到则回退到该项的原始可读值。"""
        paths = " ".join(filter(None, [hit.source, hit.markdown_key, hit.filename]))
        chat_name = self._chat_name(paths)
        doc_name = self._doc_name(paths) or self._fallback_doc_name(hit)

        parts = [p for p in (chat_name, doc_name) if p]
        return " / ".join(parts) if parts else (hit.filename or hit.doc_uuid or "未知来源")

    def _chat_name(self, text: str) -> str | None:
        m = _CHAT_ID_RE.search(text)
        if not m:
            return None
        chat_id = m.group(0)
        with self._lock:
            if chat_id in self._chat_cache:
                return self._chat_cache[chat_id]
        name = self._safe_call(get_chat_name, chat_id)
        with self._lock:
            self._chat_cache[chat_id] = name
        return name

    def _doc_name(self, text: str) -> str | None:
        m = _WIKI_TOKEN_RE.search(text)
        if not m:
            return None
        wiki_token = m.group(1)
        with self._lock:
            if wiki_token in self._doc_cache:
                return self._doc_cache[wiki_token]
        name = self._safe_call(get_wiki_node_title, wiki_token)
        with self._lock:
            self._doc_cache[wiki_token] = name
        return name

    def _safe_call(self, fn, arg: str) -> str | None:
        try:
            return fn(self.base_url, self.token, arg, timeout_seconds=self.timeout_seconds)
        except (LarkApiError, OSError):
            return None

    @staticmethod
    def _fallback_doc_name(hit: RecallHit) -> str | None:
        """拿不到 wiki 标题时，用文件名去掉飞书 ID 前缀做兜底。"""
        name = hit.filename or ""
        # 去掉形如 om_xxx_ 的飞书消息/对象前缀，保留尾部更可读的部分
        name = re.sub(r"^(om_[0-9a-z]+_)+", "", name)
        name = re.sub(r"wiki_[0-9A-Za-z]+", "", name)
        name = name.strip(" _-")
        return name or None
