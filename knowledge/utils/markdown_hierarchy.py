"""Markdown 层级结构提取器。

基于 ``markdown-it-py`` 解析 Markdown，按标题 (``#`` ~ ``######``) 构建
层级树，并扁平化成一组 ``MarkdownSection`` 节点。每个节点带有：

- ``level`` / ``title`` / ``heading_line`` —— 当前标题信息；
- ``body``                                —— 当前标题下、下一个同级或更高级标题
                                             出现前的原始 Markdown 正文；
- ``breadcrumb``                          —— 祖先标题列表 (不含自身)；
- ``has_children``                        —— 是否还存在子标题，便于切片决定
                                             是否将"只包含子节点"的标题节点跳过。

如果运行环境没有安装 ``markdown-it-py``，会自动退化到一个基于正则的最小
实现，保证调用方不会因为可选依赖缺失而崩溃。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:  # markdown-it-py 为可选依赖
    from markdown_it import MarkdownIt  # type: ignore

    _MD_PARSER: "MarkdownIt | None" = MarkdownIt("commonmark", {"breaks": False, "html": True})
except Exception:  # pragma: no cover - 优雅降级
    _MD_PARSER = None


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class MarkdownSection:
    """扁平化后的 Markdown 层级节点。"""

    level: int
    title: str
    heading_line: str
    body: str
    breadcrumb: list[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    has_children: bool = False

    @property
    def breadcrumb_path(self) -> str:
        """``A > B > 自身标题`` 形式的面包屑。"""
        parts = [p for p in (*self.breadcrumb, self.title) if p]
        return " > ".join(parts)

    @property
    def section_text(self) -> str:
        """带标题行的完整 Markdown section 文本。"""
        if self.body:
            return f"{self.heading_line}\n{self.body}".strip()
        return self.heading_line.strip()


def extract_sections(text: str) -> list[MarkdownSection]:
    """解析 Markdown 并返回扁平化的层级节点。

    顺序与文档原始顺序一致；前导无标题正文会作为 ``level=0`` / ``title=""``
    的伪节点放在最前面，便于调用方按需保留或丢弃。
    """
    if not text or not text.strip():
        return []

    headings = _collect_headings(text)
    lines = text.split("\n")

    sections: list[MarkdownSection] = []

    if not headings:
        sections.append(
            MarkdownSection(
                level=0,
                title="",
                heading_line="",
                body=text.strip(),
                start_line=0,
                end_line=len(lines),
            )
        )
        return sections

    if headings[0][0] > 0:
        prefix_body = "\n".join(lines[: headings[0][0]]).strip()
        if prefix_body:
            sections.append(
                MarkdownSection(
                    level=0,
                    title="",
                    heading_line="",
                    body=prefix_body,
                    start_line=0,
                    end_line=headings[0][0],
                )
            )

    for idx, (line_no, level, title) in enumerate(headings):
        end_line = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        body_lines = lines[line_no + 1 : end_line]
        sections.append(
            MarkdownSection(
                level=level,
                title=title,
                heading_line=lines[line_no],
                body="\n".join(body_lines).strip(),
                start_line=line_no,
                end_line=end_line,
            )
        )

    _attach_breadcrumbs(sections)
    return sections


def iter_leaf_sections(
    sections: list[MarkdownSection],
    *,
    keep_intermediate_with_body: bool = True,
) -> list[MarkdownSection]:
    """从扁平节点列表中挑出"有正文意义"的节点。

    - 无正文且仅作为父级容器的标题节点 (``has_children=True``) 会被跳过；
    - 若 ``keep_intermediate_with_body=True``，带正文的父节点也会保留，
      这样调用方既能拿到 leaf 的内容，也能拿到父级 intro 段。
    """
    result: list[MarkdownSection] = []
    for sec in sections:
        body = sec.body.strip()
        if not body:
            continue
        if not sec.has_children:
            result.append(sec)
            continue
        if keep_intermediate_with_body:
            result.append(sec)
    return result


def _collect_headings(text: str) -> list[tuple[int, int, str]]:
    """返回 ``[(line_no, level, title), ...]``，优先使用 markdown-it-py。"""
    if _MD_PARSER is not None:
        try:
            tokens = _MD_PARSER.parse(text)
        except Exception:  # pragma: no cover - 兜底
            tokens = []
        headings: list[tuple[int, int, str]] = []
        for i, tok in enumerate(tokens):
            if tok.type != "heading_open" or not tok.map:
                continue
            level = int(tok.tag[1:]) if tok.tag and tok.tag.startswith("h") else 1
            title = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                title = (tokens[i + 1].content or "").strip()
            headings.append((tok.map[0], level, title))
        if headings:
            return headings

    headings = []
    for match in _HEADING_RE.finditer(text):
        line_no = text.count("\n", 0, match.start())
        headings.append((line_no, len(match.group(1)), match.group(2).strip()))
    return headings


def _attach_breadcrumbs(sections: list[MarkdownSection]) -> None:
    stack: list[MarkdownSection] = []
    for sec in sections:
        if sec.level <= 0:
            sec.breadcrumb = []
            stack = []
            continue

        while stack and stack[-1].level >= sec.level:
            stack.pop()

        sec.breadcrumb = [s.title for s in stack if s.title]
        for ancestor in stack:
            ancestor.has_children = True
        stack.append(sec)


__all__ = [
    "MarkdownSection",
    "extract_sections",
    "iter_leaf_sections",
]
