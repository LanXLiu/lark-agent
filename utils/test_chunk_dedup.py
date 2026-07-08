from chunker.base import ChunkResult
from utils.chunk_dedup import (
    deduplicate_chunks,
    deduplicate_document_chunks,
    normalize_chunk_text,
)


def _chunk(index: int, text: str, title: str = "") -> ChunkResult:
    return ChunkResult(
        text=text,
        index=index,
        token_count=len(text),
        metadata={"title": title} if title else {},
    )


def test_normalize_removes_markdown_escapes_and_extra_whitespace():
    assert normalize_chunk_text("  ## XX客户\\_OMS   项目\n\n  ") == "## XX客户_OMS 项目"


def test_exact_duplicate_keeps_first_chunk():
    chunks = [
        _chunk(0, "## 项目背景\n正文"),
        _chunk(1, " ## 项目背景\n正文 "),
        _chunk(2, "## 需求分析\n正文"),
    ]

    result = deduplicate_chunks(chunks)

    assert [chunk.text for chunk in result] == ["## 项目背景\n正文", "## 需求分析\n正文"]
    assert [chunk.index for chunk in result] == [0, 1]


def test_heading_only_chunk_dropped_when_later_chunk_has_same_title():
    chunks = [
        _chunk(0, "## 项目背景", "项目背景"),
        _chunk(1, "## 项目背景\n- 现状：系统较多", "项目背景"),
        _chunk(2, "## 需求分析\n正文", "需求分析"),
    ]

    result = deduplicate_chunks(chunks)

    assert [chunk.metadata.get("title") for chunk in result] == ["项目背景", "需求分析"]
    assert result[0].text.startswith("## 项目背景\n")


def test_short_chunk_dropped_when_contained_in_later_long_chunk():
    chunks = [
        _chunk(0, "## 功能明细"),
        _chunk(1, "## 功能明细\n序号：1 模块：系统管理 子模块：用户管理"),
    ]

    result = deduplicate_chunks(chunks)

    assert len(result) == 1
    assert "序号：1" in result[0].text


def test_document_dedup_combines_rules_without_lsh():
    chunks = [
        _chunk(0, "## 项目背景", "项目背景"),
        _chunk(1, "## 项目背景\n- 现状：系统较多", "项目背景"),
        _chunk(2, "## 项目背景\n- 现状：系统较多", "项目背景"),
    ]

    result = deduplicate_document_chunks(chunks, enable_lsh=False)

    assert len(result) == 1
    assert result[0].text == "## 项目背景\n- 现状：系统较多"
