"""Markdown structure-aware chunker with document type routing."""

from __future__ import annotations

import re
from dataclasses import dataclass

from chunker.base import BaseChunker, ChunkResult


@dataclass
class HeaderSection:
    text: str
    title: str = ""
    level: int = 0


class MarkdownStructureChunker(BaseChunker):
    """Chunk Markdown according to the source document shape.

    The strategy is intentionally deterministic: use headers and record lines
    before falling back to recursive text splitting.
    """

    name = "markdown_structure"

    _TEXT_SEPARATORS = ["\n\n", "\n", "。", ".", "；", ";", " ", ""]
    _RECORD_PATTERN = re.compile(r"(^|\s)[^：:\s|]{1,40}[：:]\s*\S+")
    _PAGE_PATTERN = re.compile(r"<!--\s*page:\s*(\d+)\s*-->", re.IGNORECASE)
    _SLIDE_PATTERN = re.compile(r"^##\s+Slide\s+(\d+)\b", re.IGNORECASE | re.MULTILINE)
    _SHEET_HEADING_PATTERN = re.compile(r"^#{1,3}\s+Sheet:\s*(.+?)\s*$", re.MULTILINE)
    _CONTEXT_ONLY_TITLE_PATTERN = re.compile(
        r"^(?:page\s*\d+|第[一二三四五六七八九十百千万\d]+[页章节章])$",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        from conf.yaml_config import get

        cfg = get("chunker", {}).get("strategies", {}).get("markdown_structure", {})
        self.min_chunk_size = int(cfg.get("min_chunk_size", cfg.get("min_section_size", 80)))
        self.max_chunk_size = int(cfg.get("max_chunk_size", cfg.get("chunk_size", 1500)))
        self.chunk_overlap = int(cfg.get("chunk_overlap", 100))
        self.header_levels = cfg.get("header_levels", ["#", "##", "###"])
        self.table_record_one_chunk = bool(cfg.get("table_record_one_chunk", True))
        # 管道表格(| 列 | 列 |)原子化：把每行数据 + 表头渲染成「字段：值」独立 chunk，
        # 避免大表格被切断、或单行脱离表头失去列含义。默认开启。
        self.table_pipe_atomic = bool(cfg.get("table_pipe_atomic", True))
        self.image_single_chunk_max_chars = int(
            cfg.get("image_single_chunk_max_chars", self.max_chunk_size)
        )
        self.ppt_page_max_chars = int(cfg.get("ppt_page_max_chars", self.max_chunk_size))

    async def chunk(self, text: str, **kwargs) -> list[ChunkResult]:
        """Auto-detect the source document type and route to its chunking strategy."""
        max_size = int(kwargs.get("max_chunk_size", kwargs.get("chunk_size", self.max_chunk_size)))
        min_size = int(kwargs.get("min_chunk_size", self.min_chunk_size))
        overlap = int(kwargs.get("chunk_overlap", self.chunk_overlap))
        file_ext = str(kwargs.get("file_ext", "")).lower()
        doc_type = kwargs.get("doc_type")

        if not doc_type:
            from chunker.doc_type_detector import DocTypeDetector

            doc_type = DocTypeDetector().detect(text, file_ext)

        if doc_type == "ppt":
            return self._chunk_ppt(text, max_size, overlap)
        if doc_type in ("excel", "sheet"):
            return self._chunk_excel(text)
        if doc_type == "image":
            return self._chunk_image(text, max_size, overlap)
        if doc_type == "word":
            return self._chunk_word(text, max_size, min_size, overlap)
        if doc_type == "pdf":
            return self._chunk_pdf(text, max_size, min_size, overlap)
        if doc_type == "sop_report":
            return self._chunk_by_headers(
                text, max_size, min_size, overlap, {"doc_type": "sop_report"}
            )
        if doc_type == "structured_biz":
            return self._chunk_by_headers(
                text, max_size, min_size, overlap, {"doc_type": "structured_biz"}
            )
        return self._chunk_by_headers(text, max_size, min_size, overlap, {"doc_type": "general"})

    # ------------------------------------------------------------------ routes
    def _chunk_ppt(self, text: str, max_size: int, overlap: int) -> list[ChunkResult]:
        max_size = min(max_size, self.ppt_page_max_chars)
        sections = self._split_by_headers(text, levels={2})
        if not sections:
            sections = [
                HeaderSection(slide.strip(), self._first_line(slide), 2)
                for slide in re.split(r"\n-{3,}\n", text)
                if slide.strip()
            ]

        chunks: list[ChunkResult] = []
        visual_mode = bool(self._PAGE_PATTERN.search(text))
        for section in sections:
            page = self._extract_page(section.text)
            slide = self._extract_slide(section.title)
            metadata = {
                "doc_type": "ppt",
                "ppt_mode": "visual" if visual_mode else "text",
                "chunk_kind": "page" if visual_mode else "slide",
                "title": section.title,
            }
            if page is not None:
                metadata["page"] = page
            if slide is not None:
                metadata["slide"] = slide
            self._append_text_chunks(
                chunks,
                section.text,
                max_size,
                overlap,
                metadata,
                min_size=0,
                force=True,
            )
        return chunks

    def _chunk_excel(self, text: str) -> list[ChunkResult]:
        chunks: list[ChunkResult] = []
        sheet_blocks = self._split_sheet_blocks(text)
        if not sheet_blocks:
            sheet_blocks = [("", text)]

        for sheet_name, body in sheet_blocks:
            body_lines = [ln.strip() for ln in body.splitlines()
                          if ln.strip() and not ln.strip().startswith("#")]
            pipe_lines = [ln for ln in body_lines
                          if ln.startswith("|") and ln.endswith("|")]
            # 管道表格原子化：整块是管道表格时，用「表头 + 每行」渲染成「字段：值」，
            # 使每行 chunk 自带列含义(避免单行脱离表头失去语义)。
            if self.table_pipe_atomic and len(pipe_lines) >= 2 and len(pipe_lines) == len(body_lines):
                self._append_pipe_table_chunks(
                    chunks, pipe_lines,
                    {"doc_type": "excel", "sheet": sheet_name}, 0,
                )
                continue
            # 非管道表格(或未开原子化)：保持原逐行 record 逻辑
            row_index = 0
            for line in body.splitlines():
                record = line.strip()
                if not record or record.startswith("#"):
                    continue
                metadata = {
                    "doc_type": "excel",
                    "chunk_kind": "table_record",
                    "sheet": sheet_name,
                    "row_index": row_index,
                }
                self._append_raw_chunk(chunks, record, metadata)
                row_index += 1
        return chunks

    def _chunk_image(self, text: str, max_size: int, overlap: int) -> list[ChunkResult]:
        chunks: list[ChunkResult] = []
        metadata = {"doc_type": "image", "chunk_kind": "ocr", "page": 1}
        limit = min(max_size, self.image_single_chunk_max_chars)
        self._append_text_chunks(
            chunks,
            text,
            limit,
            overlap,
            metadata,
            min_size=0,
            force=True,
        )
        return chunks

    def _chunk_word(
        self, text: str, max_size: int, min_size: int, overlap: int
    ) -> list[ChunkResult]:
        from utils.markdown_hierarchy import extract_sections, iter_leaf_sections

        hierarchy_sections = iter_leaf_sections(extract_sections(text))
        chunks: list[ChunkResult] = []

        for hsec in hierarchy_sections:
            section_text = hsec.section_text
            if not section_text.strip():
                continue

            base_metadata = {
                "doc_type": "word",
                "chunk_kind": "section",
                "title": hsec.title or self._first_line(section_text),
                "level": hsec.level,
                "breadcrumb": hsec.breadcrumb_path,
            }

            normal_lines: list[str] = []
            pipe_lines: list[str] = []  # 连续的管道表格行(| 列 | 列 |)缓冲
            record_index = 0

            def _flush_normal() -> None:
                nonlocal normal_lines
                if normal_lines:
                    self._append_hierarchy_section_chunk(
                        chunks, "\n".join(normal_lines), base_metadata,
                        max_size, min_size, overlap,
                    )
                    normal_lines = []

            def _flush_pipe() -> None:
                nonlocal pipe_lines, record_index
                if not pipe_lines:
                    return
                block = pipe_lines
                pipe_lines = []
                if self.table_pipe_atomic:
                    record_index = self._append_pipe_table_chunks(
                        chunks, block, base_metadata, record_index,
                    )
                else:
                    # 未开原子化：整块管道表格当普通文本切
                    self._append_hierarchy_section_chunk(
                        chunks, "\n".join(block), base_metadata,
                        max_size, min_size, overlap,
                    )

            for line in section_text.splitlines():
                stripped = line.strip()
                if not stripped:
                    _flush_pipe()
                    normal_lines.append(line)
                    continue
                if stripped.startswith("|") and stripped.endswith("|"):
                    # 管道表格行：先把累积的普通文本切出去，再进表格缓冲
                    _flush_normal()
                    pipe_lines.append(stripped)
                    continue
                # 非管道行：先把累积的表格块原子化
                _flush_pipe()
                if self.table_record_one_chunk and self._is_record_line(stripped):
                    _flush_normal()
                    record_metadata = dict(base_metadata)
                    record_metadata["chunk_kind"] = "table_record"
                    record_metadata["record_index"] = record_index
                    self._append_raw_chunk(chunks, stripped, record_metadata)
                    record_index += 1
                else:
                    normal_lines.append(line)

            _flush_pipe()
            _flush_normal()

        if not chunks and text.strip():
            self._append_text_chunks(
                chunks,
                text,
                max_size,
                overlap,
                {"doc_type": "word", "chunk_kind": "section"},
                min_size=min_size,
                force=True,
            )
        return chunks

    def _append_hierarchy_section_chunk(
        self,
        chunks: list[ChunkResult],
        text: str,
        base_metadata: dict,
        max_size: int,
        min_size: int,
        overlap: int,
    ) -> None:
        metadata = dict(base_metadata)
        metadata["chunk_kind"] = "section"
        self._append_text_chunks(chunks, text, max_size, overlap, metadata, min_size=min_size)

    def _chunk_pdf(
        self, text: str, max_size: int, min_size: int, overlap: int
    ) -> list[ChunkResult]:
        if self._has_markdown_headers(text):
            return self._chunk_by_headers(
                text, max_size, min_size, overlap, {"doc_type": "pdf", "chunk_kind": "section"}
            )

        chunks: list[ChunkResult] = []
        for part in self._sentence_length_split(text, max_size, overlap):
            self._append_text_chunks(
                chunks,
                part,
                max_size,
                overlap,
                {"doc_type": "pdf", "chunk_kind": "text"},
                min_size=min_size,
                force=True,
            )
        return chunks

    # --------------------------------------------------------------- primitives
    def _chunk_by_headers(
        self,
        text: str,
        max_size: int,
        min_size: int,
        overlap: int,
        base_metadata: dict,
    ) -> list[ChunkResult]:
        chunks: list[ChunkResult] = []
        for section in self._split_by_headers(text):
            metadata = dict(base_metadata)
            metadata.setdefault("chunk_kind", "section")
            if section.title:
                metadata["title"] = section.title
            page = self._extract_page(section.text)
            if page is not None:
                metadata["page"] = page
            self._append_text_chunks(
                chunks, section.text, max_size, overlap, metadata, min_size=min_size, force=False
            )

        if not chunks and text.strip():
            self._append_text_chunks(
                chunks,
                text,
                max_size,
                overlap,
                dict(base_metadata),
                min_size=min_size,
                force=True,
            )
        return chunks

    def _append_word_section(
        self,
        chunks: list[ChunkResult],
        text: str,
        section: HeaderSection,
        max_size: int,
        min_size: int,
        overlap: int,
    ) -> None:
        metadata = {"doc_type": "word", "chunk_kind": "section", "title": section.title}
        self._append_text_chunks(chunks, text, max_size, overlap, metadata, min_size=min_size)

    def _append_text_chunks(
        self,
        chunks: list[ChunkResult],
        text: str,
        max_size: int,
        overlap: int,
        metadata: dict,
        *,
        min_size: int,
        force: bool = False,
    ) -> None:
        text = text.strip()
        if not text:
            return

        if len(text) <= max_size:
            # min_size is a tuning signal, not a content filter: short sections
            # still carry titles, OCR, or table context that should be indexed.
            self._append_raw_chunk(chunks, text, metadata)
            return

        parts = self._recursive_split_protected(text, max_size, overlap, self._TEXT_SEPARATORS)
        for part_index, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            part_metadata = dict(metadata)
            part_metadata["part_index"] = part_index
            self._append_raw_chunk(chunks, part, part_metadata)

    @staticmethod
    def _append_raw_chunk(chunks: list[ChunkResult], text: str, metadata: dict) -> None:
        text = text.strip()
        if not text:
            return
        chunks.append(
            ChunkResult(
                text=text,
                index=len(chunks),
                token_count=len(text),
                metadata=dict(metadata),
            )
        )

    @staticmethod
    def _split_pipe_row(line: str) -> list[str]:
        """把 `| a | b | c |` 拆成 ['a','b','c'](去掉首尾空管道)。"""
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    @staticmethod
    def _is_pipe_separator(line: str) -> bool:
        """判断是否为 markdown 表头分隔行,如 `| --- | :--: |`。"""
        cells = MarkdownStructureChunker._split_pipe_row(line)
        return bool(cells) and all(
            c != "" and set(c) <= set("-: ") for c in cells
        )

    def _append_pipe_table_chunks(
        self,
        chunks: list[ChunkResult],
        pipe_lines: list[str],
        base_metadata: dict,
        record_index: int,
    ) -> int:
        """把一块 markdown 管道表格原子化：表头 + 每行数据 → 一个「字段：值」chunk。

        每行都带上表头语义(如「姓名：张三 状态：已审批」)，使单行脱离表格后仍可检索、
        且避免大表格被从中间切断。返回更新后的 record_index。
        表头缺失/解析异常时，回退为把整块当普通文本(交由调用方的兜底)。
        """
        from file_to_markdown.table_renderer import records_to_text, rows_to_records

        # 找表头(第一非分隔行)与数据行
        rows_raw = [ln for ln in pipe_lines if ln.strip()]
        if len(rows_raw) < 2:
            # 不成表格(不足表头+1行)，当普通文本切
            self._append_hierarchy_section_chunk(
                chunks, "\n".join(pipe_lines), base_metadata,
                self.max_chunk_size, self.min_chunk_size, self.chunk_overlap,
            )
            return record_index

        headers = self._split_pipe_row(rows_raw[0])
        data_lines = [
            ln for ln in rows_raw[1:] if not self._is_pipe_separator(ln)
        ]
        try:
            records = rows_to_records(
                headers, [self._split_pipe_row(ln) for ln in data_lines]
            )
        except Exception:  # noqa: BLE001 —— 解析异常回退为普通文本，不丢内容
            self._append_hierarchy_section_chunk(
                chunks, "\n".join(pipe_lines), base_metadata,
                self.max_chunk_size, self.min_chunk_size, self.chunk_overlap,
            )
            return record_index

        for rec in records:
            row_text = records_to_text([rec])
            if not row_text.strip():
                continue
            row_metadata = dict(base_metadata)
            row_metadata["chunk_kind"] = "table_row"
            row_metadata["record_index"] = record_index
            self._append_raw_chunk(chunks, row_text, row_metadata)
            record_index += 1
        return record_index

    # --------------------------------------------------------------- splitters
    def _split_by_headers(self, text: str, levels: set[int] | None = None) -> list[HeaderSection]:
        """Small local equivalent of MarkdownHeaderTextSplitter."""
        allowed_levels = levels or self._configured_header_levels()
        matches = list(re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, flags=re.MULTILINE))
        matches = [m for m in matches if len(m.group(1)) in allowed_levels]
        if not matches:
            return [HeaderSection(text.strip(), "", 0)] if text.strip() else []

        sections: list[HeaderSection] = []
        prefix = text[: matches[0].start()].strip()
        if prefix:
            sections.append(HeaderSection(prefix, "", 0))

        for idx, match in enumerate(matches):
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            block = text[match.start() : end].strip()
            if block:
                sections.append(
                    HeaderSection(
                        text=block,
                        title=match.group(2).strip(),
                        level=len(match.group(1)),
                    )
                )
        return self._merge_context_only_sections(sections)

    def _merge_context_only_sections(self, sections: list[HeaderSection]) -> list[HeaderSection]:
        """Attach page/chapter-only headings to neighboring content sections."""
        merged: list[HeaderSection] = []
        pending: list[HeaderSection] = []

        for section in sections:
            if self._is_context_only_section(section):
                pending.append(section)
                continue

            if pending:
                prefix = "\n\n".join(item.text for item in pending)
                section.text = f"{prefix}\n\n{section.text}".strip()
                pending = []
            merged.append(section)

        if pending:
            suffix = "\n\n".join(item.text for item in pending)
            if merged:
                merged[-1].text = f"{merged[-1].text}\n\n{suffix}".strip()
            else:
                merged.extend(pending)

        return merged

    def _split_sheet_blocks(self, text: str) -> list[tuple[str, str]]:
        matches = list(self._SHEET_HEADING_PATTERN.finditer(text))
        if not matches:
            return []

        blocks: list[tuple[str, str]] = []
        for idx, match in enumerate(matches):
            body_start = match.end()
            body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            blocks.append((match.group(1).strip(), text[body_start:body_end].strip()))
        return blocks

    def _sentence_length_split(self, text: str, max_size: int, overlap: int) -> list[str]:
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[。！？!?；;.!?])\s+", text.strip())
            if s.strip()
        ]
        if not sentences:
            return self._recursive_split_protected(text, max_size, overlap, self._TEXT_SEPARATORS)

        parts: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_size:
                current = candidate
                continue
            if current:
                parts.append(current)
            if len(sentence) > max_size:
                parts.extend(
                    self._recursive_split_protected(
                        sentence,
                        max_size,
                        overlap,
                        self._TEXT_SEPARATORS,
                    )
                )
                current = ""
            else:
                current = sentence
        if current:
            parts.append(current)
        return parts

    def _recursive_split_protected(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: list[str],
    ) -> list[str]:
        """Recursively split text at natural boundaries."""
        if len(text) <= chunk_size or not separators:
            return [text] if text.strip() else []

        sep = separators[0]
        remaining_seps = separators[1:]

        if sep == "":
            parts = []
            start = 0
            step = max(1, chunk_size - chunk_overlap)
            while start < len(text):
                end = min(start + chunk_size, len(text))
                parts.append(text[start:end])
                start += step
            return parts

        segments = text.split(sep)
        merged = []
        current = ""

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            candidate = seg if not current else current + sep + seg

            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    merged.append(current)
                if len(seg) > chunk_size:
                    merged.extend(
                        self._recursive_split_protected(
                            seg,
                            chunk_size,
                            chunk_overlap,
                            remaining_seps,
                        )
                    )
                    current = ""
                else:
                    current = seg

        if current:
            merged.append(current)
        return merged

    # ---------------------------------------------------------------- helpers
    def _configured_header_levels(self) -> set[int]:
        levels: set[int] = set()
        for marker in self.header_levels:
            if isinstance(marker, str) and marker.startswith("#"):
                levels.add(len(marker))
            elif isinstance(marker, int):
                levels.add(marker)
        return levels or {1, 2, 3}

    @classmethod
    def _extract_page(cls, text: str) -> int | None:
        match = cls._PAGE_PATTERN.search(text)
        return int(match.group(1)) if match else None

    @classmethod
    def _extract_slide(cls, title: str) -> int | None:
        match = re.search(r"\bSlide\s+(\d+)\b", title, flags=re.IGNORECASE)
        return int(match.group(1)) if match else None

    @classmethod
    def _is_record_line(cls, line: str) -> bool:
        if line.startswith("#") or line.startswith("|"):
            return False
        return len(cls._RECORD_PATTERN.findall(line)) >= 1

    @staticmethod
    def _has_markdown_headers(text: str) -> bool:
        return bool(re.search(r"^#{1,3}\s+\S+", text, flags=re.MULTILINE))

    @classmethod
    def _is_context_only_section(cls, section: HeaderSection) -> bool:
        lines = [line.strip() for line in section.text.splitlines() if line.strip()]
        if len(lines) != 1:
            return False
        title = section.title.strip()
        if not title:
            return False
        return bool(cls._CONTEXT_ONLY_TITLE_PATTERN.match(title))

    @staticmethod
    def _first_line(text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line:
                return line.lstrip("#").strip()
        return ""

    @staticmethod
    def _auto_detect_doc_type(text: str, file_ext: str = "") -> str:
        from chunker.doc_type_detector import DocTypeDetector

        return DocTypeDetector().detect(text, file_ext)