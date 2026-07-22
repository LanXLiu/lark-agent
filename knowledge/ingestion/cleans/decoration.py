"""装饰横线 / 全角分隔行剔除。

覆盖的形态::

    ---     ***     ___       === === ===     （ASCII，≥3 个）
    ═══════════     ━━━━━━    ──────           （Unicode 横线 / 粗线，≥3 个）
    ——————          …………        ··········    （破折号 / 省略号 / 点串）
    ▀▀▀ ▄▄▄ ░░░ ▒▒▒ ▓▓▓                       （Unicode 制表 / 块字符）

对 PPT 视觉版输出里偶尔出现的「装饰条 + 装饰条」也能一并处理。

注意：``---`` 在我们现有几个 exporter 里被当作 Sheet / Page 之间的分隔；
删掉之后下游切片不受影响——`## Sheet:` / `## Page` 标题本身就是更强的语义边界。
"""

from __future__ import annotations

import re

# 单字符装饰行：3 个以上同类装饰字符
_DECORATION_RE = re.compile(
    r"^\s*(?:"
    # ASCII 系
    r"[-*_=]{3,}"
    # 中文 / Unicode 横线 / 破折号 / 点状串
    r"|[═━─—…·\u2013\u2014\u2500\u2501\u2502\u2503]{3,}"
    # Unicode 制表（U+2500–U+259F）和块字符（U+2580–U+259F）至少 2 个
    r"|[\u2500-\u259f]{2,}"
    r")\s*$"
)


def is_decoration_line(line: str) -> bool:
    if not line:
        return False
    return bool(_DECORATION_RE.match(line))


def remove_decorative_lines(text: str) -> tuple[str, int]:
    """删除装饰横线 / 全角分隔行；返回 ``(cleaned_text, 删除行数)``。"""
    if not text:
        return text, 0
    n = 0
    out: list[str] = []
    for ln in text.split("\n"):
        if is_decoration_line(ln):
            n += 1
            continue
        out.append(ln)
    return "\n".join(out), n


__all__ = ["is_decoration_line", "remove_decorative_lines"]
