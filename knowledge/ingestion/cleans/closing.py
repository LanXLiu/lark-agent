"""结束 / 致谢 / Q&A 收尾页清洗。

PPT / 长文档常见的"结束语"行：

- ``THANK YOU !`` / ``Thank you`` / ``Thanks`` / ``Many thanks``
- ``谢谢`` / ``谢谢大家`` / ``谢谢观看`` / ``谢谢聆听`` / ``谢谢倾听``
- ``感谢`` / ``感谢您的聆听`` / ``感谢您的观看`` / ``感谢您 的 聆听``（兼容空格）
- ``Q&A`` / ``Q & A`` / ``Questions`` / ``Questions?``
- ``THE END`` / ``End`` / ``Fin``
- ``完`` / ``完毕`` / ``完结``

匹配规则
--------
1. **整行**匹配（前后允许 ``#``/空白/markdown 强调符 ``*_~`` ``）；
2. 行长 ≤ 30 字（防止长句正文里的"谢谢您一直以来的支持..."被误删）；
3. 允许前缀 ``#`` ~ ``######``（结束页常是 ``## Thank you`` 这种标题形态）；
4. 多空白 / 中文标点尾巴（``！。？!.,?``）可任意；
5. 中文模式不允许混入数字 / 拉丁字母，避免误伤"谢谢 1 楼"这种正文。

匹配后 **整行删除**；落库时把命中数写入 ``metadata.removed_closing_lines``。
"""

from __future__ import annotations

import re

# 中文结束语后允许跟随的"语义白名单"（结尾常见客套词）：
# - 主体词：您 / 您们 / 大家 / 各位 / 我们 / 你 / 你们
# - 动作 / 对象：观看 / 聆听 / 倾听 / 阅读 / 关注 / 支持 / 配合 / 参与 / 理解 / 指导 / 鼓励 /
#                陪伴 / 时间 / 耐心 / 莅临 / 莅会 / 出席
# - 连接 / 修饰：的 / 您的 / 大家的
# 任意 CJK 文字**不在**白名单的话即视为"句子还没结束"，正则就匹配不到 `\s*$`，从而避免误伤。
_CN_CLOSING_TAIL = (
    r"[\s"
    r"您们的大家各位我们你"
    r"观看聆听倾听阅读关注支持配合参与理解指导鼓励陪伴时间耐心莅临出席"
    r".,!?！。，、；：]*"
)

# 注意：每条子模式都是「裸 pattern」，最终拼装在 _CLOSING_FULL_RE 里统一加 `^...$`。
_CLOSING_SUBPATS: tuple[str, ...] = (
    # 英文 thanks 系列
    r"thank\s*(?:you|s)?[\s.,!?！。，]*",
    r"many\s+thanks[\s.,!?！。，]*",
    r"thanks\s+for\s+(?:your\s+)?(?:attention|listening|watching|time)[\s.,!?！。，]*",
    # End / Fin
    r"(?:the\s+)?end[\s.,!?！。，]*",
    r"fin[\s.,!?！。，]*",
    # Q&A
    r"q\s*&\s*a[\s.,!?！。，]*",
    r"questions?\s*\??[\s.,!?！。，]*",
    # 中文「谢谢」/「感谢」/「致谢」+ 语义白名单（限定语义，规避长句正文误伤）
    r"谢\s*谢" + _CN_CLOSING_TAIL,
    r"感\s*谢" + _CN_CLOSING_TAIL,
    r"致\s*谢" + _CN_CLOSING_TAIL,
    # 完 / 完毕 / 完结
    r"完\s*[毕结]?[\s.,!?！。，]*",
)

_CLOSING_FULL_RE = re.compile(
    r"^\s*#{0,6}\s*(?:" + "|".join(_CLOSING_SUBPATS) + r")\s*$",
    re.IGNORECASE,
)

# Markdown 强调字符在 strip 前先剥一层
_EMPH_CHARS = "*_~` "


def _strip_emphasis(s: str) -> str:
    out = s.strip()
    # 反复剥 *_~ ` 直到稳定
    while out and out[0] in _EMPH_CHARS:
        out = out[1:].lstrip()
    while out and out[-1] in _EMPH_CHARS:
        out = out[:-1].rstrip()
    return out


def is_closing_line(line: str) -> bool:
    """判断一行是否是「结束 / 致谢 / Q&A」类无信息收尾。"""
    if not line:
        return False
    s = _strip_emphasis(line)
    if not s or len(s) > 30:
        return False
    return bool(_CLOSING_FULL_RE.match(s))


def remove_closing_thanks(text: str) -> tuple[str, int]:
    """删除所有匹配到的结束 / 致谢 / Q&A 行；返回 ``(cleaned_text, 删除行数)``。"""
    if not text:
        return text, 0
    n = 0
    out: list[str] = []
    for ln in text.split("\n"):
        if is_closing_line(ln):
            n += 1
            continue
        out.append(ln)
    return "\n".join(out), n


__all__ = ["is_closing_line", "remove_closing_thanks"]
