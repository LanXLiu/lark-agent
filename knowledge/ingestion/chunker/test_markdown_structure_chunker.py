import asyncio

from knowledge.ingestion.chunker.chunker_factory import ChunkerFactory
from knowledge.ingestion.chunker.markdown_structure_chunker import MarkdownStructureChunker


def _chunk(text: str, **kwargs):
    chunker = MarkdownStructureChunker()
    return asyncio.run(chunker.chunk(text, **kwargs))


def test_factory_registers_markdown_structure():
    chunker = ChunkerFactory.create("markdown_structure")

    assert isinstance(chunker, MarkdownStructureChunker)


def test_ppt_visual_chunks_one_page_per_h2_with_page_metadata():
    text = """## 业务总览
<!-- page: 1 -->
第一页内容

## 履约看板
<!-- page: 2 -->
第二页内容
"""

    chunks = _chunk(text, file_ext=".pptx", chunk_size=1500)

    assert len(chunks) == 2
    assert chunks[0].metadata["doc_type"] == "ppt"
    assert chunks[0].metadata["ppt_mode"] == "visual"
    assert chunks[0].metadata["page"] == 1
    assert chunks[0].metadata["title"] == "业务总览"


def test_ppt_text_chunks_one_slide_per_h2():
    text = """## Slide 1
文本版第一页内容

## Slide 2
文本版第二页内容
"""

    chunks = _chunk(text, file_ext=".pptx", chunk_size=1500)

    assert len(chunks) == 2
    assert chunks[0].metadata["ppt_mode"] == "text"
    assert chunks[0].metadata["slide"] == 1
    assert chunks[0].metadata["title"] == "Slide 1"


def test_ppt_oversized_page_is_recursively_split():
    text = "## 大页\n<!-- page: 1 -->\n" + "这是一句很长的页面内容。" * 40

    chunks = _chunk(text, file_ext=".pptx", chunk_size=120, chunk_overlap=20)

    assert len(chunks) > 1
    assert all(chunk.metadata["page"] == 1 for chunk in chunks)
    assert all("part_index" in chunk.metadata for chunk in chunks)


def test_excel_chunks_each_record_and_preserves_sheet_metadata():
    text = """## Sheet: 入库
单号：A001 状态：完成
单号：A002 状态：待处理

## Sheet: 出库
单号：B001 状态：完成
"""

    chunks = _chunk(text, file_ext=".xlsx")

    assert [chunk.text for chunk in chunks] == [
        "单号：A001 状态：完成",
        "单号：A002 状态：待处理",
        "单号：B001 状态：完成",
    ]
    assert [chunk.metadata["sheet"] for chunk in chunks] == ["入库", "入库", "出库"]
    assert all(chunk.metadata["chunk_kind"] == "table_record" for chunk in chunks)


def test_image_short_ocr_stays_single_chunk_and_long_ocr_splits():
    short_chunks = _chunk("门头照片 OCR 内容", file_ext=".png", chunk_size=1500)
    long_text = "\n\n".join([f"第{i}段 OCR 内容很长很长" for i in range(30)])
    long_chunks = _chunk(long_text, file_ext=".png", chunk_size=120, chunk_overlap=20)

    assert len(short_chunks) == 1
    assert short_chunks[0].metadata["doc_type"] == "image"
    assert len(long_chunks) > 1
    assert all(chunk.metadata["chunk_kind"] == "ocr" for chunk in long_chunks)


def test_word_table_records_are_independent_chunks():
    text = """# 客户档案
这是正文说明。
客户：张三 金额：100 状态：已完成
客户：李四 金额：200 状态：待处理
后续正文说明。
"""

    chunks = _chunk(text, file_ext=".docx", chunk_size=1500, min_chunk_size=1)

    record_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_kind"] == "table_record"]
    section_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_kind"] == "section"]
    assert len(record_chunks) == 2
    assert record_chunks[0].text == "客户：张三 金额：100 状态：已完成"
    assert section_chunks


def test_word_uses_hierarchy_breadcrumb_metadata():
    text = """# 客户档案
档案模块的总体介绍说明。

## 基础信息
基础信息说明。
- 姓名：张三
- 年龄：30

## 联系信息
联系方式说明。
- 电话：12345
"""

    chunks = _chunk(text, file_ext=".docx", chunk_size=1500, min_chunk_size=1)
    by_title = {chunk.metadata.get("title"): chunk for chunk in chunks}

    assert "基础信息" in by_title
    assert by_title["基础信息"].metadata["breadcrumb"] == "客户档案 > 基础信息"
    assert by_title["基础信息"].metadata["level"] == 2
    assert by_title["联系信息"].metadata["breadcrumb"] == "客户档案 > 联系信息"

    # 父级带正文的章节也应该保留
    assert "客户档案" in by_title
    assert by_title["客户档案"].metadata["breadcrumb"] == "客户档案"


def test_pdf_uses_headers_when_available():
    text = """## 第一章
章节一内容。

## 第二章
章节二内容。
"""

    chunks = _chunk(text, file_ext=".pdf", chunk_size=1500, min_chunk_size=1)

    assert len(chunks) == 2
    assert [chunk.metadata["title"] for chunk in chunks] == ["第一章", "第二章"]
    assert all(chunk.metadata["chunk_kind"] == "section" for chunk in chunks)


def test_pdf_without_headers_uses_sentence_length_split():
    text = "。".join([f"这是第{i}个句子，内容用于模拟 PDF 文本" for i in range(20)]) + "。"

    chunks = _chunk(text, file_ext=".pdf", chunk_size=120, chunk_overlap=20, min_chunk_size=1)

    assert len(chunks) > 1
    assert all(chunk.metadata["doc_type"] == "pdf" for chunk in chunks)
    assert all(chunk.metadata["chunk_kind"] == "text" for chunk in chunks)


def test_pdf_page_heading_is_attached_to_following_section():
    text = """## Page 7

## 订单流程
这里是第七页正文内容。

## Page 8

## 库存流程
这里是第八页正文内容。
"""

    chunks = _chunk(text, file_ext=".pdf", chunk_size=1500, min_chunk_size=1)

    assert len(chunks) == 2
    assert chunks[0].text.startswith("## Page 7\n\n## 订单流程")
    assert chunks[0].metadata["title"] == "订单流程"
    assert chunks[1].text.startswith("## Page 8\n\n## 库存流程")
    assert chunks[1].metadata["title"] == "库存流程"


def test_pdf_chapter_heading_only_is_not_single_chunk():
    text = """## 第一章

## 系统背景
这里是章节正文。
"""

    chunks = _chunk(text, file_ext=".pdf", chunk_size=1500, min_chunk_size=1)

    assert len(chunks) == 1
    assert chunks[0].text.startswith("## 第一章\n\n## 系统背景")


def test_pipe_table_atomized_per_row_with_header():
    # 管道表格：每行数据应原子化成一个「字段：值」chunk，且带上表头语义
    text = """## 报销记录

| 姓名 | 事由 | 状态 |
| --- | --- | --- |
| 张三 | 差旅报销 | 已审批 |
| 李四 | 办公用品 | 待审批 |
"""
    chunks = _chunk(text, file_ext=".md", chunk_size=1500, min_chunk_size=1)

    table_rows = [c for c in chunks if c.metadata.get("chunk_kind") == "table_row"]
    assert len(table_rows) == 2, f"应有 2 行原子 chunk，实际 {len(table_rows)}"
    # 每行都带上了表头字段名(脱离表格也知道每列含义)
    assert "姓名：张三" in table_rows[0].text
    assert "事由：差旅报销" in table_rows[0].text
    assert "状态：已审批" in table_rows[0].text
    assert "姓名：李四" in table_rows[1].text
    # 分隔行(| --- |)不应产生 chunk
    assert all("---" not in c.text for c in table_rows)

