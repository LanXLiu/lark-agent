"""
HTML 片段转 Markdown 与轻量清洗。

基于 ``markdownify``，可剥离图片标签与 Base64 图片数据，供 Word/OCR 后处理复用。
"""

from markdownify import markdownify as md
import logging
import re
import os
import html

# 配置日志
logger = logging.getLogger(__name__)

class HtmlToMarkdownConverter():
    """HTML转Markdown转换器"""
    
    def convert(self, html_content: str, filename: str = "") -> str:
        """
        将HTML内容转换为Markdown格式
        
        Args:
            html_content: HTML内容字符串
            filename: 文件名（可选）
            
        Returns:
            Markdown格式的字符串
        """
        try:
            # 先清理HTML内容中的图片
            cleaned_html = self.clean_image(html_content)
            # 表格预处理：所有 <table> 节点在交给 markdownify 之前先用
            # 「字段名：内容 字段名：内容」纯文本段落替换，避免生成 pipe 表，
            # 也避免下游 finalize 兜底再做一次回滚——直接源头消灭。
            cleaned_html = self._tables_to_field_value(cleaned_html)
            try:
                markdown_content = md(
                    cleaned_html,
                    heading_style="ATX",
                    bullets="-",
                    strip=["script", "style"],
                )
            except TypeError:
                markdown_content = md(cleaned_html, heading_style="ATX", bullets="-")
            return markdown_content
        except Exception as e:
            logger.error(f"HTML转Markdown失败: {e}")
            return html_content

    @staticmethod
    def _tables_to_field_value(html_content: str) -> str:
        """
        把 HTML 里所有 ``<table>`` 节点替换为「字段名：内容 …」纯文本段落，
        每条 record 一个 ``<p>``，便于 markdownify 直接转为多段 Markdown。

        - 首个 ``<tr>`` 视为表头；其余 ``<tr>`` 视为数据行；
        - 嵌套段落 / ``<br>`` 由 ``BeautifulSoup.get_text(separator=" ")`` 拍平；
        - 单元格全空的 ``<tr>`` 自动忽略；
        - 解析失败或缺少 ``bs4`` 时静默回退，保留原始 HTML（仍能跑通 markdownify）。
        """
        if "<table" not in html_content.lower():
            return html_content
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html_content

        from .table_renderer import table_to_field_value_text

        soup = BeautifulSoup(html_content, "html.parser")

        for table in soup.find_all("table"):
            rows_raw: list[list[str]] = []
            for tr in table.find_all("tr"):
                cells: list[str] = []
                for cell in tr.find_all(["th", "td"]):
                    cells.append(cell.get_text(separator=" ", strip=True))
                if any(c.strip() for c in cells):
                    rows_raw.append(cells)

            if not rows_raw:
                table.decompose()
                continue

            headers = rows_raw[0]
            data_rows = rows_raw[1:]
            text = table_to_field_value_text(headers, data_rows)

            # 用 <div> 包一组 <p>，每行一条 record；markdownify 会把它们
            # 渲染成多段纯文本。空表格则直接删除原节点。
            replacement = soup.new_tag("div")
            for line in text.splitlines() if text else []:
                p = soup.new_tag("p")
                p.string = line
                replacement.append(p)
            table.replace_with(replacement)

        return str(soup)

    def convert_if_needed(self, content: str, conversion_method: str) -> str:
        """
        检测内容中是否包含HTML标签，如果有则转换为Markdown格式
    
        Args:
            content: 要检测的内容
            conversion_method: 原始转换方法，用于日志记录
        
        Returns:
            转换后的Markdown内容
        """
        try:
            # 检测是否包含HTML标签
            html_pattern = re.compile(r'<[^>]+>')
            has_html_tags = bool(html_pattern.search(content))
        
            if has_html_tags:
                print(f"检测到HTML标签，进行HTML到Markdown转换 (原始方法: {conversion_method})")
            
                # 进行转换
                markdown_content = self.convert(content)
            
                # 检查转换前后的变化
                original_length = len(content)
                converted_length = len(markdown_content)
                html_tag_count = len(html_pattern.findall(content))
            
                print(f"HTML转MD结果: 原始长度={original_length}, 转换后长度={converted_length}, HTML标签数={html_tag_count}")
            
                return markdown_content
            else:
                # 没有HTML标签，直接返回原内容
                return content
            
        except Exception as e:
            print(f"HTML到Markdown转换失败: {e}")
            return content

    @staticmethod
    def clean_image(html_content: str) -> str:
        """
        清理HTML内容，删除图片
        
        Args:
            html_content: 包含HTML标签的文本
            
        Returns:
            str: 清理后的文本
        """
        if not html_content:
            return ""
        
        # 先解码HTML实体
        text = html.unescape(html_content)

        # 处理图片标签 - 直接删除
        text = re.sub(r'<img\s+[^>]*src="[^"]*"[^>]*alt="[^"]*"[^>]*>', '', text)
        text = re.sub(r'<img\s+[^>]*alt="[^"]*"[^>]*src="[^"]*"[^>]*>', '', text)
        text = re.sub(r'<img\s+[^>]*src="[^"]*"[^>]*>', '', text)
    
        # 删除base64格式的图片数据
        text = re.sub(r'data:image/[^;]+;base64,[a-zA-Z0-9+/]*={0,2}', '', text)
        
        return text.strip()