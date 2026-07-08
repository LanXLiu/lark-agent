"""
PDF 相关转换与检测工具。

含 MarkItDown 文本型 PDF 转 MD、扫描件检测、MarkItDown 兜底及扫描件分页渲染 OCR 统一入口。
"""

import io
import re
from typing import Dict, List, Tuple, Optional
from markitdown import MarkItDown
import os
import tempfile
import fitz


class PdfToMarkdownConverter:
    """PDF转Markdown转换器 - 仅用于非扫描PDF"""

    def __init__(self):
        self.markitdown = MarkItDown()

    def convert(self, file_content: bytes, filename: str) -> str:
        """
        转换PDF文件为Markdown
        注意：这个转换器只处理非扫描PDF，扫描PDF应该在主路由中处理
        """
        try:
            result = self.markitdown.convert(io.BytesIO(file_content))
            
            if not result.text_content:
                return "# PDF转换结果\n\n无法从PDF中提取文本内容。"
                
            return result.text_content
        except Exception as e:
            return f"# PDF转换结果\n\n转换过程中出现错误: {str(e)}"

# 辅助函数 - 这些函数应该被主路由使用
def is_pdf_scanned(file_content: bytes) -> bool:
    """检测PDF是否为扫描图像"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name
        
        try:
            doc = fitz.open(temp_path)
            has_meaningful_text = False
            
            for i in range(min(3, len(doc))):
                page = doc[i]
                text = page.get_text()
                
                if text:
                    # 检查是否有连续的句子
                    sentences = re.findall(r'[^。！？!?]+[。！？!?]', text)
                    if len(sentences) > 1:
                        has_meaningful_text = True
                        break
                        
                    # 检查是否有合理的词汇
                    meaningful_words = re.findall(r'[a-zA-Z\u4e00-\u9fff]{2,}', text)
                    if len(meaningful_words) > 10:
                        has_meaningful_text = True
                        break
            
            doc.close()
            return not has_meaningful_text
            
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        print(f"PDF检测失败: {e}")
        return True

def is_text_content_insufficient(text: str, threshold: int = 50) -> bool:
    """检测文本内容是否不足"""
    if not text:
        return True
        
    clean_text = re.sub(r'\s+', '', text).strip()
    
    # 检查是否包含扫描特征
    error_indicators = ["扫描件", "图片内容", "未提取到文本", "无法提取文本"]
    has_error_indicator = any(indicator in text for indicator in error_indicators)
    
    # 检查扫描特征
    has_scan_indicators = detect_scan_indicators(text)
    
    
    
    return len(clean_text) < threshold or has_error_indicator or has_scan_indicators
def detect_short_line_sequences(text: str) -> int:
    """检测三个字以内的连续换行超过10行的情况"""
    if not text:
        return 0
    
    lines = text.split('\n')
    short_line_sequences = 0
    current_sequence_length = 0
    
    for line in lines:
        # 清理行内容，计算有效字符数
        clean_line = line.strip()
        char_count = len(re.sub(r'\s', '', clean_line))
        
        # 判断是否为短行（3个字符以内）
        if char_count <= 3 and char_count > 0:  # 非空短行
            current_sequence_length += 1
        else:
            # 序列结束，检查是否满足条件
            if current_sequence_length >= 15:
                short_line_sequences += 1
            current_sequence_length = 0
    
    # 检查文件末尾的序列
    if current_sequence_length >= 15:
        short_line_sequences += 1
    
    return short_line_sequences

def detect_scan_indicators(text: str) -> bool:
    """检测扫描件特征 """
    if not text:
        return True
    
    # 统计各种特征
    features = {
        'page_breaks': len(re.findall(r'\f', text)),
        'multiple_newlines': len(re.findall(r'(\n\s*){3,}', text)),
        'short_line_sequences': detect_short_line_sequences(text),
        'empty_line_ratio': 0,  # 空行占比
    }
    
    # 计算空行占比
    lines = text.split('\n')
    total_lines = len(lines)
    empty_lines = sum(1 for line in lines if line.strip() == '')
    empty_line_ratio = empty_lines / total_lines if total_lines > 0 else 0
    features['empty_line_ratio'] = empty_line_ratio
    
    # 计算特征分数
    score = 0
    thresholds = {
        'page_breaks': 2,
        'multiple_newlines': 3,
        'short_line_sequences': 1,  # 只要检测到1次就计分
        'empty_line_ratio': 0.2,   # 空行占比超过20%
    }
    
    print("扫描特征统计:")
    for feature, count in features.items():
        if feature == 'empty_line_ratio':
            # 特殊处理比例类型的特征
            if count > thresholds[feature]:
                score += 1
                print(f"  {feature}: {count:.3f} (超过阈值 {thresholds[feature]}) ✓")
            else:
                print(f"  {feature}: {count:.3f}")
        else:
            if count > thresholds[feature]:
                score += 1
                print(f"  {feature}: {count} (超过阈值 {thresholds[feature]}) ✓")
            else:
                print(f"  {feature}: {count}")
    
    # 检查中文字符比例
    total_chars = len(re.sub(r'\s', '', text))
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    chinese_ratio = chinese_chars / total_chars if total_chars > 0 else 0
    
    print(f"中文字符比例: {chinese_ratio:.3f}, 特征分数: {score}")
    
    return score >= 2 or chinese_ratio < 0.1

def convert_other_to_markdown(file_content: bytes) -> str:
    """使用原有方式转换PDF和其他文件类型"""
    try:
        # 初始化MarkItDown转换器
        md = MarkItDown()
        # 转换文件内容
        result = md.convert(io.BytesIO(file_content))
        
        return result.text_content or "# 文件转换结果\n\n无法从文件中提取文本内容。"
    except Exception as e:
        return f"# 文件转换结果\n\n转换过程中出现错误: {str(e)}"


def convert_scanned_pdf_pages_to_markdown(
    file_content: bytes,
    filename: str,
    *,
    max_pages: int = 25,
    zoom: float = 2.0,
) -> str:
    """扫描件 PDF：逐页渲染为 PNG 后走 PP-Structure OCR。"""
    from .image_to_markdown import get_image_to_markdown_converter

    doc = fitz.open(stream=file_content, filetype="pdf")
    try:
        total = len(doc)
        n = min(total, max_pages)
        ocr = get_image_to_markdown_converter()
        parts: list[str] = []
        mat = fitz.Matrix(zoom, zoom)
        for i in range(n):
            page = doc[i]
            pix = page.get_pixmap(matrix=mat, alpha=False)
            png_bytes = pix.tobytes("png")
            body = ocr.convert(png_bytes, f"page_{i + 1}.png")
            parts.append(f"## Page {i + 1}\n\n{body.strip()}")
        md = "\n\n---\n\n".join(parts)
        if total > n:
            md += (
                f"\n\n> _Scanned PDF: omitted pages {n + 1}–{total} "
                f"(limit {max_pages})._\n"
            )
        return md
    finally:
        doc.close()


def convert_pdf_bytes_unified(
    file_content: bytes,
    filename: str,
    *,
    max_scanned_pages: int = 25,
) -> tuple[str, dict]:
    """统一 PDF → Markdown：数字版文本 / 扫描分页 OCR / MarkItDown 兜底。"""
    meta: dict = {"converter": "pdf_unified"}
    try:
        if is_pdf_scanned(file_content):
            meta["pdf_render_mode"] = "scanned_page_ocr"
            md = convert_scanned_pdf_pages_to_markdown(
                file_content,
                filename,
                max_pages=max_scanned_pages,
            )
        else:
            conv = PdfToMarkdownConverter()
            md = conv.convert(file_content, filename)
            meta["pdf_render_mode"] = "digital_text"
            if is_text_content_insufficient(md, threshold=40):
                alt = convert_other_to_markdown(file_content)
                if len(re.sub(r"\s+", "", alt)) > len(re.sub(r"\s+", "", md)) * 1.15:
                    md = alt
                    meta["pdf_render_mode"] = "markitdown_fallback"
        return md, meta
    except Exception as e:
        return f"# PDF 转换\n\n错误: {e}", {**meta, "error": str(e)}


# 测试代码
if __name__ == "__main__":
    # 初始化转换器
    converter = PdfToMarkdownConverter()
    
    # 测试配置：替换为你的测试PDF路径
    TEST_PDF_PATH = "c++意向简历.pdf"
    
    try:
        # 读取PDF文件内容
        with open(TEST_PDF_PATH, 'rb') as f:
            file_content = f.read()
        
        # 先检测是否为扫描PDF
        if is_pdf_scanned(file_content):
            print(f"PDF检测为扫描图像，应该使用图像转换器处理")
            # 这里不处理扫描PDF，只是演示
            result = "# 扫描PDF\n\n这是一个扫描PDF，应该使用图像转换器处理"
        else:
            # 调用转换方法处理非扫描PDF
            filename = os.path.basename(TEST_PDF_PATH)
            result = converter.convert(file_content, filename)
            
            print("---")
            print(is_text_content_insufficient(result))
        
        print("="*50)
        print(f"PDF转换结果")
        print("="*50)
        print(result)
        
    except FileNotFoundError:
        print(f"错误：未找到测试文件 {TEST_PDF_PATH}")
    except Exception as e:
        print(f"测试过程中出现错误: {str(e)}")