"""
Word 文档（DOCX）转 Markdown。

使用 mammoth 生成 HTML，再经 ``HtmlToMarkdownConverter`` 规范化；
可选对 ZIP 内 ``word/media`` 图片做 OCR 拼接。支持 ``with`` 清理临时资源。
"""

import io
import sys
import os
import tempfile
import mammoth
from markdownify import markdownify as md
import html
import re
import zipfile
from io import BytesIO
import shutil
from typing import Optional, Dict, List, Tuple
import traceback

from prompts.vlm import WORD_IMAGE_PROMPT

# 同包内相对导入（本仓库无 ``utils.file_to_markdown`` 包名）
from .html_to_markdown import HtmlToMarkdownConverter
from .image_to_markdown import (
    ImageToMarkdownConverter,
    get_image_to_markdown_converter,
)


_VLM_WORD_PROMPT = WORD_IMAGE_PROMPT


def _meaningful_char_count(text: str) -> int:
    """统计「中文字符 + 字母 + 数字」的总数，作为可读文字量度。"""
    if not text:
        return 0
    return len(re.findall(r"[\u4e00-\u9fff\w]", text))


class WordToMarkdownConverter:
    """Word文档转Markdown转换器（解决状态残留问题）"""

    def __init__(
        self,
        enable_ocr: bool = True,
        *,
        enable_vlm_fallback: bool = True,
        vlm_min_chars: int = 20,
    ):
        """
        :param enable_ocr:          是否启用 PPStructure OCR 识别图片中的文字。
        :param enable_vlm_fallback: 当 PPStructure OCR 对某张图片识别出的有效字符数 < ``vlm_min_chars``
                                    时，是否调用 VLM（多模态视觉模型）兜底进行"看图说话"。
                                    依赖 ``settings.MODELS.VLM`` 配置，``api_key`` 为空将自动禁用。
        :param vlm_min_chars:       双重阈值：
                                    (1) PPStructure 结果有效字符 < 此值 → 触发 VLM 兜底；
                                    (2) VLM 输出的有效字符 ≤ 此值 → 丢弃不写入文档（默认 20 字）。
        """
        self.html_converter = HtmlToMarkdownConverter()
        self.enable_ocr = enable_ocr
        self.image_ocr_results: Dict[str, Dict] = {}
        self.ocr_converter: Optional[ImageToMarkdownConverter] = None

        # 临时目录管理
        self.temp_dir: Optional[tempfile.TemporaryDirectory] = None
        self.temp_image_dir: Optional[str] = None

        # OCR转换器延迟初始化
        self._ocr_initialized = False

        # ----- VLM 兜底（仅当 PPStructure 不行时使用）-----
        self.enable_vlm_fallback = enable_vlm_fallback
        self.vlm_min_chars = int(vlm_min_chars)
        self._vlm_cfg: Optional[dict] = None
        self._vlm_checked = False

    def _init_ocr_converter(self):
        """初始化OCR转换器（仅在需要时初始化）"""
        if self._ocr_initialized or not self.enable_ocr:
            return
            
        try:
            self.ocr_converter = get_image_to_markdown_converter()
            if hasattr(self.ocr_converter, "reset"):
                self.ocr_converter.reset()
        except Exception as e:
            print(f"初始化OCR转换器失败: {e}", file=sys.stderr)
            self.ocr_converter = None
        finally:
            self._ocr_initialized = True

    def _ensure_vlm_ready(self) -> bool:
        """
        检查 VLM 兜底是否可用（只在第一次需要时执行）。

        - ``enable_vlm_fallback=False`` → 永远不启用；
        - ``settings.MODELS.VLM.api_key`` 为空 → 自动禁用并打印一次提示。

        Returns:
            ``True`` 表示后续可调用 ``_vlm_describe_image_bytes``；``False`` 表示跳过 VLM。
        """
        if not self.enable_vlm_fallback:
            return False
        if self._vlm_checked:
            return self._vlm_cfg is not None
        self._vlm_checked = True
        try:
            from .vlm_client import read_vlm_settings

            cfg = read_vlm_settings()
            if not cfg.get("api_key"):
                print(
                    "[word→md] VLM 兜底已禁用：settings.MODELS.VLM.api_key 为空",
                    file=sys.stderr,
                )
                self._vlm_cfg = None
                return False
            self._vlm_cfg = cfg
            return True
        except Exception as e:
            print(f"[word→md] VLM 兜底初始化失败：{e}", file=sys.stderr)
            self._vlm_cfg = None
            return False

    def _vlm_describe_image_bytes(self, image_bytes: bytes, mime_type: str) -> str:
        """
        对一张「PPStructure 识别不出」的图调用 VLM 做总结描述。

        共享 :func:`vlm_client.describe_image_with_retry` 的瞬态错误重试策略
        （默认 1s → 2s 线性退避，重试 2 次），最终失败返回 ``""``，
        Word 主流程读到空串就会按「VLM 也没识别出来」处理，不影响整体转换。
        """
        if not self._vlm_cfg:
            return ""
        try:
            from .vlm_client import describe_image_with_retry

            text = describe_image_with_retry(
                image_bytes,
                prompt=_VLM_WORD_PROMPT,
                mime_type=mime_type,
                url=self._vlm_cfg.get("url"),
                api_key=self._vlm_cfg.get("api_key"),
                model=self._vlm_cfg.get("model"),
                timeout_sec=self._vlm_cfg.get("timeout_sec"),
                max_retries=2,
                retry_backoff_sec=1.0,
                log_label="word→md",
            )
            return (text or "").strip()
        except Exception as e:
            print(f"[word→md] VLM 兜底最终失败：{e}", file=sys.stderr)
            return ""

    def _create_temp_dir(self):
        """创建临时目录（按需创建）"""
        if self.temp_dir is None:
            try:
                self.temp_dir = tempfile.TemporaryDirectory(
                    prefix="word2md_", 
                    suffix="_images"
                )
                self.temp_image_dir = self.temp_dir.name
            except Exception as e:
                print(f"创建临时目录失败: {e}", file=sys.stderr)
                self.temp_dir = None
                self.temp_image_dir = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        """清理所有临时资源"""
        # 1. 清空OCR缓存
        self.image_ocr_results.clear()
        
        # 2. 清理临时目录
        if self.temp_dir:
            try:
                self.temp_dir.cleanup()
            except Exception as e:
                print(f"清理临时目录失败: {e}", file=sys.stderr)
            finally:
                self.temp_dir = None
                self.temp_image_dir = None
        
        # 3. 重置OCR转换器状态
        self._ocr_initialized = False
        self.ocr_converter = None

    def _reset_conversion_state(self):
        """重置转换状态（确保每次转换独立）"""
        # 关键：重置OCR转换器的状态
        if self.ocr_converter and hasattr(self.ocr_converter, 'reset'):
            try:
                print("重置OCR转换器状态...")
                self.ocr_converter.reset()
            except Exception as e:
                print(f"重置OCR转换器状态失败: {e}", file=sys.stderr)

    def convert(self, file_content: bytes, filename: str) -> str:
        """
        主转换方法（原子化：每次转换前强制重置状态）
        :param file_content: Word文档二进制内容
        :param filename: 文件名
        :return: 纯净的Markdown内容（无历史残留）
        """
        print(f"\n{'='*60}")
        print(f"开始转换文件: {filename}")
        print(f"OCR转换器实例ID: {id(self.ocr_converter) if self.ocr_converter else None}")
        print(f"OCR转换器已初始化: {self._ocr_initialized}")
        print('='*60)
        
        # 每次转换前重置所有缓存和状态
        self._reset_conversion_state()
        self.image_ocr_results.clear()  # 清空上一次的OCR结果
        
        file_ext = os.path.splitext(filename)[1].lower()
        markdown_content = ""

        # 检查文件内容是否有效
        if not self._is_valid_word_content(file_content):
            return "# Word文档转换结果\n\n文档内容无效或已损坏。"

        # 尝试mammoth转换
        try:
            markdown_content = self._convert_with_mammoth(file_content, file_ext)
            if self._is_sufficient_text_content(markdown_content):
                # 过滤残留文本
                clean_content = self._filter_residual_text(markdown_content)
                return clean_content
        except Exception as e:
            print(f"mammoth转换失败: {e}\n{traceback.format_exc()}", file=sys.stderr)

        # 如果mammoth转换失败或内容不足，尝试降级方案
        if not markdown_content or self.is_text_content_insufficient(markdown_content):
            # 尝试OCR提取
            ocr_content = self._try_extract_with_ocr(file_content)
            
            if ocr_content:
                markdown_content = (
                    "# Word文档内容提取\n\n"
                    "> 注：文档可能为扫描件/图片为主，通过OCR技术提取文本内容\n\n"
                    f"{ocr_content}"
                )
            else:
                markdown_content = (
                    "# Word文档转换结果\n\n"
                    "> 注：文档可能为扫描件/图片为主，或格式损坏，文本提取不完整\n\n"
                )

        # 最终过滤
        final_content = self._filter_residual_text(markdown_content)
        return final_content

    def _is_valid_word_content(self, content: bytes) -> bool:
        """检查是否为有效的Word文档内容"""
        if not content or len(content) < 100:  # 最小文件大小
            return False
        
        try:
            # 检查是否为有效的ZIP文件（DOCX是ZIP格式）
            with BytesIO(content) as f:
                with zipfile.ZipFile(f) as zip_ref:
                    # 检查是否包含必要的Word文档结构
                    required_files = ['[Content_Types].xml', '_rels/.rels']
                    zip_files = zip_ref.namelist()
                    return any(req in zip_files for req in required_files)
        except:
            return False

    def _convert_with_mammoth(self, file_content: bytes, file_ext: str) -> str:
        """核心转换逻辑"""
        # 直接用内存字节喂给 mammoth，不落临时文件。
        # （Windows 上 NamedTemporaryFile 仍打开时再 open 同名文件会触发
        #  PermissionError，导致 docx 转换全部失败。）
        with BytesIO(file_content) as docx_file:
            result = mammoth.convert_to_html(
                docx_file,
                convert_image=ignore_all_images,
            )
            html_content = result.value
            _ = result.messages  # 转换告警，按需可记录

        # 转换HTML为Markdown
        markdown_content = self.html_converter.convert(html_content)

        # 如果内容不足，再尝试OCR（避免重复工作）
        if (self.enable_ocr and 
            self.is_text_content_insufficient(markdown_content)):
            self._create_temp_dir()
            if self.temp_image_dir:
                ocr_content = self._extract_images_from_content(file_content)
                if ocr_content:
                    markdown_content = f"{markdown_content}\n\n---\n\n{ocr_content}"

        return markdown_content

    def _extract_images_from_content(self, file_content: bytes) -> str:
        """从文档内容中提取图片并进行OCR"""
        if not self.enable_ocr:
            return ""
            
        # 初始化OCR转换器
        self._init_ocr_converter()
        if not self.ocr_converter:
            return ""
            
        try:
            src_zip = BytesIO(file_content)
            with zipfile.ZipFile(src_zip) as zin:
                return self._extract_images_ocr(zin)
        except Exception as e:
            print(f"提取图片/OCR失败: {e}", file=sys.stderr)
            return ""

    def _extract_images_ocr(self, zip_file: zipfile.ZipFile) -> str:
        """
        逐张抽取 ``word/media/*`` 图片做 OCR；当 PPStructure OCR 结果**有效字符不足**
        ``self.vlm_min_chars``（默认 20 字），且 VLM 兜底可用时，对**同一张图**再调 VLM 做"看图总结"。

        最终拼接规则：
            - PPStructure 文本 ≥ 阈值 → 直接采用 PPStructure 结果；
            - PPStructure 文本 <  阈值 → 调 VLM；VLM 有效字符 > 阈值才并入文档，
              否则丢弃这张图（不写入空内容/占位符）。
        """
        image_files = [
            f for f in zip_file.namelist()
            if f.startswith('word/media/') and f.lower().endswith(
                ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff')
            )
        ]

        if not image_files:
            return ""

        # 仅在本批次首次需要时去检查 VLM key、避免每张图都重复判断
        vlm_ready = self._ensure_vlm_ready()

        ocr_texts: List[str] = []
        for image_path in image_files:
            temp_image_path: Optional[str] = None
            try:
                image_data = zip_file.read(image_path)
                if len(image_data) < 10:
                    continue

                # 使用临时文件进行OCR
                with tempfile.NamedTemporaryFile(
                    suffix='.png',
                    delete=False,
                    dir=self.temp_image_dir
                ) as tmp_img:
                    tmp_img.write(image_data)
                    temp_image_path = tmp_img.name

                # 进行PPStructure OCR识别
                with open(temp_image_path, 'rb') as f:
                    ocr_result = self.ocr_converter.convert(
                        f.read(),
                        os.path.basename(image_path)
                    )

                clean_ocr = self._clean_ocr_result(ocr_result)
                ocr_chars = _meaningful_char_count(clean_ocr)

                if ocr_chars >= self.vlm_min_chars:
                    # PPStructure 识别得已足够，直接采用
                    ocr_texts.append(clean_ocr)
                    continue

                # ---------- PPStructure 不行：尝试 VLM 兜底 ----------
                if not vlm_ready:
                    # 没开兜底；如果 PPStructure 出了一点内容仍保留（向后兼容旧行为）
                    if clean_ocr:
                        ocr_texts.append(clean_ocr)
                    continue

                mime = self._guess_mime(image_path)
                vlm_text = self._vlm_describe_image_bytes(image_data, mime)
                vlm_chars = _meaningful_char_count(vlm_text)

                if vlm_chars > self.vlm_min_chars:
                    # 接受 VLM 描述，挂上一行说明便于后续溯源
                    ocr_texts.append(
                        f"> _图像识别（VLM）_：`{os.path.basename(image_path)}`\n\n{vlm_text}"
                    )
                else:
                    # VLM 也没产出有效内容；如果 PPStructure 残留了几个字符仍保留，避免漏信息
                    if clean_ocr:
                        ocr_texts.append(clean_ocr)

            except Exception as e:
                print(f"处理图片 {image_path} 失败: {e}", file=sys.stderr)
                continue
            finally:
                if temp_image_path and os.path.exists(temp_image_path):
                    try:
                        os.unlink(temp_image_path)
                    except OSError:
                        pass

        return "\n\n".join(ocr_texts) if ocr_texts else ""

    @staticmethod
    def _guess_mime(image_path: str) -> str:
        """根据扩展名挑选 VLM image_url 的 MIME；不识别一律按 PNG。"""
        ext = os.path.splitext(image_path)[1].lower()
        return {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".tiff": "image/tiff",
            ".webp": "image/webp",
        }.get(ext, "image/png")

    def _try_extract_with_ocr(self, file_content: bytes) -> str:
        """尝试仅通过OCR提取内容"""
        if not self.enable_ocr:
            return ""
            
        self._create_temp_dir()
        if not self.temp_image_dir:
            return ""
            
        self._init_ocr_converter()
        if not self.ocr_converter:
            return ""
            
        return self._extract_images_from_content(file_content)

    def _is_sufficient_text_content(self, text: str, threshold: int = 50) -> bool:
        """判断文本内容是否足够丰富（与insufficient相反）"""
        if not text:
            return False
            
        # 计算有意义字符数量
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        english_words = len(re.findall(r'\b[a-zA-Z]{2,}\b', text))
        digits = len(re.findall(r'\d+', text))
        
        total_meaningful = chinese_chars + english_words + digits
        return total_meaningful >= threshold

    def _filter_residual_text(self, text: str) -> str:
        """过滤残留的无效文本"""
        if not text:
            return ""
            
        # 过滤特定的残留模式
        patterns_to_remove = [
            r'转换完成但未提取到文本内容',
            r'图像转换结果',
            r'^#\s+$',  # 空标题
            r'^>\s*$',  # 空引用
        ]
        
        lines = text.split('\n')
        filtered_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            
            # 跳过空行和分隔符
            if not line_stripped or line_stripped in ('---', '***', '___'):
                continue
                
            # 检查是否匹配过滤模式
            should_skip = False
            for pattern in patterns_to_remove:
                if re.search(pattern, line_stripped, re.IGNORECASE):
                    should_skip = True
                    break
                    
            if not should_skip:
                filtered_lines.append(line)
        
        # 重新组合并清理多余空行
        result = '\n'.join(filtered_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()

    def _clean_ocr_result(self, ocr_text: str) -> str:
        """清理OCR结果"""
        if not ocr_text:
            return ""
            
        lines = ocr_text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            # 过滤OCR工具添加的元数据
            if any(meta in line.lower() for meta in [
                '图像转换结果', 
                'ocr result', 
                'converted from',
                '无法转换',
                '未提取到文本'
            ]):
                continue
                
            if len(line) > 1:  # 忽略单个字符（可能是噪声）
                cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)

    def is_text_content_insufficient(self, text: str, threshold: int = 30) -> bool:
        """检测文本内容是否不足（兼容原有接口）"""
        return not self._is_sufficient_text_content(text, threshold)

    def __del__(self):
        """析构兜底清理"""
        try:
            self.cleanup()
        except:
            pass


def ignore_all_images(element):
    """忽略所有图片"""
    return []


# ============================ 测试代码 ============================
if __name__ == "__main__":
    import glob
    
    def test_conversion():
        """测试转换函数"""
        # 查找测试文件
        test_files = glob.glob("*.docx")
        
        if not test_files:
            print("未找到测试文件 (*.docx)")
            return
            
        for i, test_file in enumerate(test_files, 1):
            print(f"\n{'='*60}")
            print(f"测试文件 {i}: {test_file}")
            print(f"{'='*60}")
            
            try:
                with WordToMarkdownConverter(enable_ocr=True) as converter:
                    with open(test_file, "rb") as f:
                        content = f.read()
                    
                    markdown = converter.convert(content, test_file)
                    
                    print("文件大小:", len(content))
                    print("前100字节:", content[:100])
                    
                    # 输出前200个字符预览
                    preview = markdown[:200] + "..." if len(markdown) > 200 else markdown
                    print(f"转换结果预览:\n{preview}")
                    
                    # 保存结果
                    output_file = test_file.replace('.docx', '.md')
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(markdown)
                    print(f"已保存到: {output_file}")
                    
            except Exception as e:
                print(f"转换失败: {e}")
                traceback.print_exc()
    
    test_conversion()