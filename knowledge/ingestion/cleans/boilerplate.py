"""法律免责声明 / 版权 / 保密 等模板尾段剔除。

策略
----
- **只看文档尾部** ``tail_paragraphs`` 段（默认 5），避免把正文里偶然出现的
  「免责声明」一词当成模板段误删；
- 段落按 ``\\n\\n`` 切分；
- 任一段命中下面任意模式 → 整段删除。

模式词
------
中文::

    本文档?仅供
    未经.{0,6}(允许|授权|许可).{0,6}(不得|禁止)
    版权所有 / 保留所有权利
    免责声明 / 保密(协议|条款)
    商业秘密 / 知识产权

英文::

    Copyright (©)? ...
    All Rights Reserved
    Confidential
    Disclaimer
    Proprietary
    Trademark

模式词位于段落任意位置即可命中——一段话里既有"版权所有"又有"保留所有权利"的
经典模板段会被整段干掉。
"""

from __future__ import annotations

import re

_BOILERPLATE_PATS: tuple[re.Pattern[str], ...] = (
    re.compile(r"本文档?仅(供|限)", re.IGNORECASE),
    re.compile(r"未经.{0,8}(允许|授权|许可|同意).{0,8}(不得|禁止|严禁)", re.IGNORECASE),
    re.compile(r"版权所有", re.IGNORECASE),
    re.compile(r"保留所有权利", re.IGNORECASE),
    re.compile(r"免责声明", re.IGNORECASE),
    re.compile(r"保密(协议|条款|声明)", re.IGNORECASE),
    re.compile(r"商业秘密", re.IGNORECASE),
    re.compile(r"知识产权(归|所有)", re.IGNORECASE),
    re.compile(r"Copyright\s*(©|\(c\))?", re.IGNORECASE),
    re.compile(r"All\s+Rights\s+Reserved", re.IGNORECASE),
    re.compile(r"\bConfidential\b", re.IGNORECASE),
    re.compile(r"\bDisclaimer\b", re.IGNORECASE),
    re.compile(r"\bProprietary\b", re.IGNORECASE),
)


def _looks_like_boilerplate(paragraph: str) -> bool:
    if not paragraph or not paragraph.strip():
        return False
    # 模板段一般很短（< 300 字），太长说明可能是正文里讨论"免责声明"这个主题，跳过
    if len(paragraph) > 300:
        return False
    return any(p.search(paragraph) for p in _BOILERPLATE_PATS)


def remove_legal_boilerplate(
    text: str,
    *,
    tail_paragraphs: int = 5,
) -> tuple[str, int]:
    """删除文档**末尾若干段**里的法律 / 版权 / 保密模板段。

    Args:
        text: 完整 Markdown 文本。
        tail_paragraphs: 仅扫描文档末尾这么多段（默认 5），保护正文段不被误删。

    Returns:
        ``(cleaned_text, 被删除的段落数)``。
    """
    if not text or not text.strip():
        return text, 0

    paragraphs = text.split("\n\n")
    if len(paragraphs) <= 1:
        return text, 0

    cut = max(0, len(paragraphs) - tail_paragraphs)
    head = paragraphs[:cut]
    tail = paragraphs[cut:]

    removed = 0
    kept_tail: list[str] = []
    for p in tail:
        if _looks_like_boilerplate(p):
            removed += 1
            continue
        kept_tail.append(p)

    if removed == 0:
        return text, 0
    return "\n\n".join(head + kept_tail).rstrip() + "\n", removed


__all__ = ["remove_legal_boilerplate"]
