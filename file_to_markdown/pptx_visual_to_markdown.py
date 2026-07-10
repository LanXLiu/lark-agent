"""PPT / PPTX → Markdown（视觉版，VLM 真·看图）。

流水线：

1. **LibreOffice CLI** 把 PPT/PPTX 整体导出为 PDF
   （``soffice --headless --convert-to pdf``）。
2. **Poppler ``pdftoppm``** 把 PDF 每页渲染为高清 PNG（默认 ``dpi=200``）。
3. 每页 PNG → base64 → 调用 **VLM**（默认豆包 ``doubao-*-vision-*``）
   做忠实转写（OCR 文本 + 结构化排版，无任何分析/总结）。
4. 拼装为按 ``## `` 切片友好的 Markdown：

   - ``# <文件名 stem>`` 作为整文档标题；
   - 每页一个 ``## <语义化标题>`` 小节，标题由 VLM 根据 PPT 本身给出；
   - 紧跟 ``<!-- page: N -->`` HTML 注释做原始页溯源；
   - 图片以 ``data:image/png;base64,...`` data URL 内嵌在小节末尾
     （``inline_images=False`` 时则不写图片，仅保留转写文本）。

与 ``test/ocr.py`` 相比：

- 接受 **bytes** 输入，符合 :mod:`file_to_markdown.unified_entry` 契约；
- VLM 配置从 :mod:`conf.settings` 读取（``settings.MODELS.VLM``）；
- 不落盘 assets 目录，图片默认 base64 内嵌，输出**纯字符串 Markdown** + 元数据。

依赖（系统包，缺失时抛 ``RuntimeError``）::

    sudo apt-get install -y libreoffice poppler-utils fonts-noto-cjk

Python 仅依赖 ``requests``。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from prompts.vlm import PPTX_TRANSCRIBE_PROMPT

from .vlm_client import describe_image_with_retry as _vlm_describe_image_retry
from .vlm_client import read_vlm_settings as _read_vlm_settings

# VLM 单页瞬态错误的最大重试次数 + 线性退避基数（1s → 2s）；超过则该页放弃。
_VLM_PAGE_MAX_RETRIES = 2
_VLM_PAGE_RETRY_BACKOFF_SEC = 1.0


_DEFAULT_PROMPT = PPTX_TRANSCRIBE_PROMPT


# --------------------------------------------------------------------- 外部命令
def _which(name: str) -> str:
    """查找 ``libreoffice`` / ``pdftoppm``；缺失时给出明确安装提示。"""
    candidates = [name]
    if name == "libreoffice":
        candidates = ["libreoffice", "soffice"]
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    raise RuntimeError(
        f"未找到命令 `{name}`，请先安装："
        " sudo apt-get install -y libreoffice poppler-utils fonts-noto-cjk"
    )


def _run(cmd: list[str]) -> None:
    """以 ``subprocess.run`` 跑外部命令；失败时抛 ``RuntimeError`` 含 stderr。"""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"命令失败 (rc={proc.returncode})：{' '.join(cmd)}\n"
            f" stdout={proc.stdout}\n stderr={proc.stderr}"
        )


def _ppt_bytes_to_pdf(content: bytes, ext: str, workdir: Path) -> Path:
    """用 LibreOffice 把内存中的 PPT 字节流落到临时目录并转 PDF。"""
    soffice = _which("libreoffice")

    # 用固定的临时文件名 "input.<ext>"，避免原始文件名里的 &/空格/中文等
    # 给 LibreOffice profile 路径带来的潜在问题。
    in_path = workdir / f"input{ext}"
    in_path.write_bytes(content)

    pdf_dir = workdir / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = workdir / "_lo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    _run(
        [
            soffice,
            # 独立 profile 防止"已有 soffice 在运行 → 静默失败"
            f"-env:UserInstallation=file://{profile_dir}",
            "--headless",
            "--norestore",
            "--nologo",
            "--nodefault",
            "--convert-to",
            "pdf",
            "--outdir",
            str(pdf_dir),
            str(in_path),
        ]
    )

    pdf = pdf_dir / (in_path.stem + ".pdf")
    if not pdf.is_file():
        cands = sorted(pdf_dir.glob("*.pdf"))
        if cands:
            pdf = cands[0]
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise RuntimeError(
            "LibreOffice 未生成有效 PDF：可能原因 = profile 锁 / 缺中文字体 / PPT 损坏或加密"
        )
    return pdf


def _pdf_to_pngs(pdf: Path, out_dir: Path, dpi: int) -> list[Path]:
    """``pdftoppm -png -r <dpi>`` 把 PDF 渲染为每页 PNG（按页码排序）。"""
    pdftoppm = _which("pdftoppm")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "page"
    _run([pdftoppm, "-png", "-r", str(dpi), str(pdf), str(prefix)])
    pngs = sorted(out_dir.glob("page-*.png")) or sorted(out_dir.glob("page*.png"))
    if not pngs:
        raise RuntimeError(f"pdftoppm 没有输出 PNG：{out_dir}")
    return pngs


# --------------------------------------------------------------------- Markdown 组装
def _normalize_page_section(summary: str, page_num: int) -> str:
    """
    保证一页内容**恰好**以 ``## `` 开头，且其内部不再有同级标题。

    - 若 VLM 偷懒未给 ``## ``，兜底为 ``## 第 N 页``；
    - 内部其他 ``## `` 全部降级为 ``**加粗**``，防止破坏切片粒度；
    - 紧跟 ``<!-- page: N -->`` HTML 注释做原始页溯源。
    """
    text = (summary or "").strip()
    if not text:
        text = f"## 第 {page_num} 页\n\n_(本页无可识别内容)_"
    if not text.startswith("## "):
        text = f"## 第 {page_num} 页\n\n{text}"

    lines = text.splitlines()
    head = lines[0]
    body_lines: list[str] = []
    for ln in lines[1:]:
        if ln.startswith("## "):
            body_lines.append(f"**{ln[3:].strip()}**")
        else:
            body_lines.append(ln)

    rebuilt = [head, f"<!-- page: {page_num} -->", ""]
    rebuilt.extend(body_lines)
    return "\n".join(rebuilt).rstrip()


# --------------------------------------------------------------------- 转换器
class PptxVisualConverter:
    """
    PPT/PPTX → Markdown（视觉版）转换器。

    **输出永远是「纯文本 Markdown」**：每页一个 ``## <语义化标题>`` + VLM 抄录正文，
    **不**包含任何 ``![pN](...)`` 图片引用——避免内嵌 base64 让 MD 文本体量爆炸、
    污染下游切片与向量化。

    用法::

        md, meta = PptxVisualConverter().convert_bytes(pptx_bytes, "foo.pptx")

    Args:
        url:            VLM ``/chat/completions`` 完整 URL；不传则取 settings 默认。
        api_key:        Bearer Token；**必须有值**，否则 ``convert_bytes`` 直接抛错。
        model:          VLM 模型 ID（默认豆包 ``doubao-1-5-vision-pro-32k-250115``）。
        dpi:            PDF → PNG 渲染 DPI（默认 200，越高越清晰但越慢）。
        timeout_sec:    单次 VLM 请求超时（秒）。
        prompt:         自定义提示词；不传则使用内置「忠实抄录、切片友好」提示词。
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        dpi: int | None = None,
        timeout_sec: int | None = None,
        prompt: str | None = None,
        **_legacy_kwargs: Any,  # 容忍旧调用方传入 inline_images 等已废弃参数
    ) -> None:
        cfg = _read_vlm_settings()
        self.url = url or cfg["url"]
        self.api_key = api_key or cfg["api_key"]
        self.model = model or cfg["model"]
        self.dpi = int(dpi or cfg["dpi"])
        self.timeout_sec = int(timeout_sec or cfg["timeout_sec"])
        self.prompt = prompt or _DEFAULT_PROMPT

    # ----------------------------------------------------------------- 主入口
    def convert_bytes(
        self, content: bytes, filename: str
    ) -> tuple[str, dict[str, Any]]:
        """
        把内存中的 PPT 字节流转换为 Markdown。

        Returns:
            ``(markdown, metadata)``；其中 ``metadata`` 包含 ``converter`` /
            ``slide_count`` / ``vlm_model`` / ``dpi``，以及（若有）``failed_pages``。

        Raises:
            RuntimeError: API key 未配置 / LibreOffice / Poppler 缺失 / PDF 生成失败等。
        """
        if not self.api_key:
            raise RuntimeError(
                "VLM api_key 未配置；请在 config_local.yaml 的 MODELS.VLM.api_key "
                "填入有效 Token，或在构造 PptxVisualConverter 时显式传入。"
            )

        ext = Path(filename).suffix.lower() or ".pptx"

        with tempfile.TemporaryDirectory(prefix="pptvis_") as tmp_str:
            tmp = Path(tmp_str)
            pdf = _ppt_bytes_to_pdf(content, ext, tmp)
            pngs = _pdf_to_pngs(pdf, tmp / "imgs", self.dpi)
            total_pages = len(pngs)

            items: list[tuple[int, str]] = []
            failed_pages: list[int] = []

            for i, png in enumerate(pngs, 1):
                summary = self._describe_one_page_with_retry(png, i)
                if summary is None:
                    # 失败页**完全跳过**，不写入 MD；仅在 metadata 里记录页号便于排查
                    failed_pages.append(i)
                    continue
                items.append((i, summary))

        md = self._assemble(Path(filename).stem, items)
        meta: dict[str, Any] = {
            "converter": "pptx_visual_vlm",
            "slide_count": len(items),
            "total_pages": total_pages,
            "vlm_model": self.model,
            "dpi": self.dpi,
        }
        if failed_pages:
            meta["failed_pages"] = failed_pages
            meta["failed_page_count"] = len(failed_pages)
        return md, meta

    # ----------------------------------------------------------------- 单页带重试
    def _describe_one_page_with_retry(self, png: Path, page_num: int) -> str | None:
        """
        对单页 PNG 调 VLM，瞬态错误按共享重试策略处理；**最终失败**返回 ``None``，
        由 :meth:`convert_bytes` 跳过该页。
        """
        try:
            return _vlm_describe_image_retry(
                png.read_bytes(),
                prompt=self.prompt,
                mime_type="image/png",
                url=self.url,
                api_key=self.api_key,
                model=self.model,
                timeout_sec=self.timeout_sec,
                max_retries=_VLM_PAGE_MAX_RETRIES,
                retry_backoff_sec=_VLM_PAGE_RETRY_BACKOFF_SEC,
                log_label=f"pptx-visual page {page_num}",
            )
        except Exception as e:
            print(
                f"[pptx-visual] 第 {page_num} 页 VLM 调用最终失败，"
                f"该页将不写入 Markdown：{e!r}",
                file=sys.stderr,
            )
            return None

    # ----------------------------------------------------------------- 拼装
    @staticmethod
    def _assemble(title: str, items: list[tuple[int, str]]) -> str:
        """拼装为纯文本 Markdown：``# title`` + 每页 ``## ...`` 小节，**不嵌图片**。"""
        lines: list[str] = [f"# {title}", ""]
        for page_num, summary in items:
            lines.append(_normalize_page_section(summary, page_num))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


__all__ = ["PptxVisualConverter"]
