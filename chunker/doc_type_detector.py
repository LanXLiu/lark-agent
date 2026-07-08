"""Document type detector for Markdown content.

Analyzes markdown structure patterns to classify documents into types
that guide subsequent chunking strategies.
"""

import re


class DocTypeDetector:
    """
    Detect document type from Markdown text based on structural patterns.

    Priority order: file extension hints > ppt > sheet > sop_report > structured_biz > general

    Returns one of: "ppt", "word", "excel", "image", "pdf", "sheet",
    "sop_report", "structured_biz", "general"
    """

    # PPT slide markers
    PPT_SLIDE_PATTERN = re.compile(r"^## Slide \d+", re.MULTILINE)
    PPT_SEPARATOR_PATTERN = re.compile(r"\n---\n")

    # Table/sheet markers
    TABLE_HEADER_PATTERN = re.compile(r"^\|.*\|.*\|$", re.MULTILINE)
    TABLE_SEPARATOR_PATTERN = re.compile(r"^\|[\s\-:]+\|[\s\-:]+\|", re.MULTILINE)

    # SOP report markers
    SOP_CODE_PATTERN = re.compile(r"SOP[-\s]*(?:IN|OUT|VAS|SYS)[-\s]*\d{3}", re.IGNORECASE)
    SOP_STEP_PATTERN = re.compile(r"步骤\s*│|标准动作\s*│|异常处理\s*│")
    SOP_KEYWORD_PATTERN = re.compile(r"SOP要点|标准作业程序|业务流|SOP框架总结", re.IGNORECASE)

    # Structured business document markers
    STRUCTURED_TITLE = re.compile(r"^[一二三四五六七八九十]+[、.．]", re.MULTILINE)
    STRUCTURED_SUBTITLE = re.compile(r"^\d+\.\d+\s", re.MULTILINE)
    STRUCTURED_LIST = re.compile(r"^\d+\.[ 　]", re.MULTILINE)

    # Code block markers (SOP reports often have flow diagrams)
    CODE_BLOCK_PATTERN = re.compile(r"```[\w]*\n.*?```", re.DOTALL)

    def detect(self, text: str, file_ext: str = "") -> str:
        """
        Detect document type from markdown text.

        Args:
            text: The markdown content to analyze.
            file_ext: Original file extension, e.g. ".pptx", ".pdf".

        Returns:
            Document type string used by MarkdownStructureChunker.
        """
        if not text or not text.strip():
            return "general"

        ext = file_ext.lower()
        if ext in (".pptx", ".ppt"):
            return "ppt"
        if ext in (".docx", ".doc"):
            return "word"
        if ext in (".xlsx", ".xls"):
            return "excel"
        if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"):
            return "image"
        if ext == ".pdf":
            return "pdf"

        # 1) PPT转写: 连续幻灯片标记 + 分页符
        slide_count = len(self.PPT_SLIDE_PATTERN.findall(text))
        sep_count = len(self.PPT_SEPARATOR_PATTERN.findall(text))
        if slide_count >= 2 and sep_count >= slide_count - 1:
            return "ppt"
        # 2) 表格/Sheet导出: 高密度表格行
        total_lines = text.count("\n") + 1
        table_rows = len(self.TABLE_HEADER_PATTERN.findall(text))
        table_seps = len(self.TABLE_SEPARATOR_PATTERN.findall(text))
        if total_lines > 0:
            table_density = table_rows / total_lines
            if table_seps >= 1 and table_density > 0.25:
                # Check if it's mostly table content
                if table_density > 0.4:
                    return "sheet"

        # 3) SOP报告: SOP编号体系 + 业务流程描述
        sop_code_matches = self.SOP_CODE_PATTERN.findall(text)
        sop_step_matches = self.SOP_STEP_PATTERN.findall(text)
        sop_keyword_matches = self.SOP_KEYWORD_PATTERN.findall(text)
        code_block_count = len(self.CODE_BLOCK_PATTERN.findall(text))

        # SOP reports typically have: SOP codes + process tables + code blocks
        sop_score = (
            len(sop_code_matches) * 3
            + len(sop_step_matches) * 2
            + len(sop_keyword_matches) * 2
            + code_block_count
        )
        if sop_score >= 4:
            return "sop_report"

        # 4) 结构化业务文档: 多级标题编号体系
        title_matches = self.STRUCTURED_TITLE.findall(text)
        subtitle_matches = self.STRUCTURED_SUBTITLE.findall(text)
        list_matches = self.STRUCTURED_LIST.findall(text)

        if len(title_matches) >= 2 and len(subtitle_matches) >= 2:
            return "structured_biz"
        # Also check for "一、" style with numbered sub-sections
        if len(title_matches) >= 1 and len(list_matches) >= 3:
            return "structured_biz"

        return "general"

    @staticmethod
    def describe(text: str, file_ext: str = "") -> dict:
        """
        Return a detailed structural analysis for debugging/display.
        """
        detector = DocTypeDetector()
        return {
            "doc_type": detector.detect(text, file_ext),
            "stats": {
                "slide_count": len(detector.PPT_SLIDE_PATTERN.findall(text)),
                "separator_count": len(detector.PPT_SEPARATOR_PATTERN.findall(text)),
                "table_rows": len(detector.TABLE_HEADER_PATTERN.findall(text)),
                "table_separators": len(detector.TABLE_SEPARATOR_PATTERN.findall(text)),
                "sop_codes": len(detector.SOP_CODE_PATTERN.findall(text)),
                "code_blocks": len(detector.CODE_BLOCK_PATTERN.findall(text)),
                "structured_titles": len(detector.STRUCTURED_TITLE.findall(text)),
                "structured_subtitles": len(detector.STRUCTURED_SUBTITLE.findall(text)),
                "total_lines": text.count("\n") + 1,
                "total_chars": len(text),
            },
            "file_extension": file_ext,
        }