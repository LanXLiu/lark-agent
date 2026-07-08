"""统一文档 → Markdown 入口（以 ``file_to_markdown`` 为唯一编排层）。

``converter`` 模块应通过 :func:`convert_file_to_markdown` 或 :func:`convert_bytes`
调度本层，以获得一致的解析、后处理与 ``metadata`` 结构。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DocumentConversionResult:
    """标准转换输出，供入库管线消费。"""

    markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)


def convert_file_to_markdown(path: Path | str, **kwargs: Any) -> DocumentConversionResult:
    path = Path(path)
    raw = path.read_bytes()
    return convert_bytes(path.suffix.lower(), raw, path.name, **kwargs)


def convert_bytes(
    ext: str,
    content: bytes,
    filename: str,
    **kwargs: Any,
) -> DocumentConversionResult:
    ext = ext.lower()
    if ext and not ext.startswith("."):
        ext = "." + ext

    from .markdown_postprocess import finalize_for_kb

    metadata: dict[str, Any] = {
        "source_filename": filename,
        "extension": ext,
        "pipeline": "file_to_markdown.unified",
    }
    md = ""

    try:
        if ext == ".pdf":
            from .pdf_to_markdown import convert_pdf_bytes_unified

            md, pm = convert_pdf_bytes_unified(
                content,
                filename,
                max_scanned_pages=int(kwargs.get("max_scanned_pages", 25)),
            )
            metadata.update(pm)

        elif ext == ".docx":
            from .word_to_markdown import WordToMarkdownConverter

            with WordToMarkdownConverter(
                enable_ocr=bool(kwargs.get("enable_word_ocr", True)),
                # 当 PPStructure 对某张图识别字符不足时，是否再调 VLM 做"看图说话"。
                # 依赖 settings.MODELS.VLM.api_key；api_key 为空时自动禁用，不会报错。
                enable_vlm_fallback=bool(kwargs.get("enable_word_vlm_fallback", True)),
                vlm_min_chars=int(kwargs.get("word_vlm_min_chars", 20)),
            ) as w:
                md = w.convert(content, filename)
            metadata["converter"] = "word_to_markdown"

        elif ext in (
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
            ".bmp",
            ".webp",
        ):
            from .image_to_markdown import get_image_to_markdown_converter

            md = get_image_to_markdown_converter().convert(content, filename)
            metadata["converter"] = "image_ppstructure"

        elif ext in (".xlsx", ".xls"):
            from .structured_exporters import excel_bytes_to_markdown

            md, xm = excel_bytes_to_markdown(content)
            metadata.update(xm)

        elif ext in (".pptx", ".ppt"):
            # PPT 有两条转换路径：
            #   1) 视觉版（pptx_visual=True）：LibreOffice → PDF → PNG → VLM，
            #      输出按 `## ` 切片友好、含语义化标题，但需要系统包 + 网络 + VLM key，
            #      速度大约「每页几秒到十几秒」。
            #   2) 文本版（默认）：python-pptx 抽取 shape/table 文本，快且离线。
            #
            # 任何时候视觉版失败（缺依赖 / 网络 / key 错误）都**自动回退到文本版**，
            # 保证调用方至少能拿到可用 Markdown，并通过 metadata.visual_fallback_reason 暴露原因。
            use_visual = bool(kwargs.get("pptx_visual", False))
            if use_visual:
                try:
                    from .pptx_visual_to_markdown import PptxVisualConverter

                    # 视觉版固定输出**纯文本 Markdown**（不嵌图片）：
                    # 内嵌 base64 会让响应体动辄 10+ MB，污染切片，因此整条链路下线 inline_images。
                    md, pm = PptxVisualConverter(
                        url=kwargs.get("pptx_vlm_url"),
                        api_key=kwargs.get("pptx_vlm_key"),
                        model=kwargs.get("pptx_vlm_model"),
                        dpi=kwargs.get("pptx_dpi"),
                        timeout_sec=kwargs.get("pptx_vlm_timeout"),
                        prompt=kwargs.get("pptx_vlm_prompt"),
                    ).convert_bytes(content, filename)
                    metadata.update(pm)
                except Exception as visual_err:
                    from .structured_exporters import pptx_bytes_to_markdown

                    md, pm = pptx_bytes_to_markdown(content)
                    metadata.update(pm)
                    metadata["converter"] = "pptx_visual_fallback_to_structured"
                    metadata["visual_fallback_reason"] = str(visual_err)
            else:
                from .structured_exporters import pptx_bytes_to_markdown

                md, pm = pptx_bytes_to_markdown(content)
                metadata.update(pm)

        elif ext == ".json":
            from .json_to_markdown import JsonToMarkdownConverter

            raw_txt = content.decode("utf-8", errors="replace")
            try:
                data: Any = json.loads(raw_txt)
            except json.JSONDecodeError:
                data = raw_txt
            title = Path(filename).stem
            md = JsonToMarkdownConverter().convert(data, title=title)
            metadata["converter"] = "json_to_markdown"

        else:
            md = f"# 不支持的格式\n\n扩展名 `{ext}` 暂无统一转换器。"
            metadata["error"] = "unsupported_extension"

    except Exception as e:
        md = f"# 转换失败\n\n`{filename}`: {e}"
        metadata["error"] = str(e)

    md = finalize_for_kb(md)

    # KB-oriented 多步清洗：跨页重复短行 / 页码 / 目录 / 装饰线 / 空块 / 法律模板尾段。
    # 默认全开；调用方可通过 ``enable_kb_cleaning=False`` 整体关闭，或传 ``kb_cleaning_kwargs``
    # 对每一步阈值做精细控制。命中类型与数量会写入 ``metadata["cleaning"]`` 供入库审计。
    if kwargs.get("enable_kb_cleaning", True):
        try:
            from cleans import clean_markdown

            cleaning_kwargs = kwargs.get("kb_cleaning_kwargs") or {}
            cr = clean_markdown(md, **cleaning_kwargs)
            md = cr.text
            if cr.metadata:
                metadata["cleaning"] = cr.metadata
        except Exception as ce:
            metadata["cleaning_error"] = f"{type(ce).__name__}: {ce}"

    metadata["markdown_char_count"] = len(md)
    return DocumentConversionResult(markdown=md, metadata=metadata)
