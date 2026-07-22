"""
数据转换 HTTP 接口：一种格式对应一个路由。

底层统一调用 ``file_to_markdown.unified_entry.convert_bytes``，在线程池中执行以免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from fastapi.encoders import jsonable_encoder

from ..schemas.convert import ConvertResponse
from knowledge.ingestion.file_to_markdown.unified_entry import convert_bytes

router = APIRouter()

# PDF / 图片转换（OCR、PPStructure 等）允许更长处理时间
_SLOW_CONVERT_TIMEOUT_SEC = 300.0
# VLM 多模态转换（PPT 视觉版 / Word 图片兜底）按页计费式调用，整体放宽到 10 分钟
_VLM_CONVERT_TIMEOUT_SEC = 600.0

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
_EXCEL_EXTS = {".xlsx", ".xls"}
_SLIDE_EXTS = {".pptx", ".ppt"}


async def _convert_with_ext(
    file: UploadFile,
    forced_ext: str | None,
    allowed: set[str] | None,
    **kwargs,
) -> ConvertResponse:
    """
    读取上传文件并在后台线程执行 ``convert_bytes``。

    Args:
        file: multipart 文件字段，须带 ``filename`` 以便判断扩展名。
        forced_ext: 若指定则忽略文件名后缀，强制使用该扩展名（如 ``.pdf``）。
        allowed: 若指定，文件名后缀必须在此集合内，否则 415。
        **kwargs: 透传给 ``convert_bytes``（如 ``max_scanned_pages``）。

    Returns:
        ``ConvertResponse``。

    Raises:
        HTTPException: 400 无文件名；415 扩展名不允许。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="请求中缺少文件名（filename）")

    raw_name = file.filename
    suffix = Path(raw_name).suffix.lower()
    if forced_ext:
        ext = forced_ext if forced_ext.startswith(".") else f".{forced_ext}"
    else:
        ext = suffix

    if allowed is not None and suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件扩展名: {suffix}，允许: {sorted(allowed)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    result = await asyncio.to_thread(convert_bytes, ext, content, raw_name, **kwargs)
    return ConvertResponse(
        markdown=result.markdown,
        metadata=result.metadata,
        filename=raw_name,
    )


async def _with_convert_timeout(
    awaitable,
    *,
    label: str,
    timeout_sec: float = _SLOW_CONVERT_TIMEOUT_SEC,
):
    """
    给慢路径包一层整体超时，超时返回 504。

    - PDF / 图片：默认 ``_SLOW_CONVERT_TIMEOUT_SEC``（5 分钟）。
    - PPT 视觉版 / Word VLM 兜底：传 ``timeout_sec=_VLM_CONVERT_TIMEOUT_SEC``（10 分钟）。
    """
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_sec)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"{label}转换超过 {timeout_sec:.0f} 秒未结束，"
                "请缩小文件、减少扫描页数或稍后重试。"
            ),
        ) from None


# 向后兼容旧名：原 `_with_slow_convert_timeout` 在他处可能被引用，保持别名
_with_slow_convert_timeout = _with_convert_timeout


# -----------------------------------------------------------------------------
# PDF
# -----------------------------------------------------------------------------
@router.post(
    "/pdf",
    response_model=ConvertResponse,
    summary="PDF 转 Markdown",
    description="上传 PDF；数字版走文本提取，扫描件可走分页 OCR（见 max_scanned_pages）。单请求最长 5 分钟。",
)
async def convert_pdf(
    file: UploadFile = File(..., description="PDF 文件"),
    max_scanned_pages: int = Query(25, ge=1, le=100, description="扫描 PDF 最多 OCR 页数"),
):
    """
    **请求示例（multipart）**

    - 字段名：`file`（文件）
    - Query：`max_scanned_pages`（可选，默认 25）
    """
    return await _with_convert_timeout(
        _convert_with_ext(
            file,
            forced_ext=".pdf",
            allowed={".pdf"},
            max_scanned_pages=max_scanned_pages,
        ),
        label="PDF",
    )


# -----------------------------------------------------------------------------
# Word（DOCX）
# -----------------------------------------------------------------------------
@router.post(
    "/docx",
    response_model=ConvertResponse,
    summary="DOCX 转 Markdown",
    description=(
        "上传 Word 文档；图片优先用 PaddleOCR PPStructure 识别。"
        "当某张图识别出的有效字符 < `word_vlm_min_chars` 时，"
        "自动调用 VLM（多模态视觉模型）做兜底「看图说话」，仅当 VLM 输出有效字符 "
        "> `word_vlm_min_chars` 才会写入 Markdown。整体最长 10 分钟。"
    ),
)
async def convert_docx(
    file: UploadFile = File(..., description="DOCX 文件"),
    enable_word_ocr: bool = Query(True, description="是否对嵌入图片做 PPStructure OCR"),
    enable_word_vlm_fallback: bool = Query(
        True,
        description="OCR 不够字时是否启用 VLM 兜底；依赖 settings.MODELS.VLM.api_key",
    ),
    word_vlm_min_chars: int = Query(
        20,
        ge=1,
        le=200,
        description="双重阈值：OCR 字符数 < 此值触发 VLM；VLM 字符数 > 此值才入库（默认 20）",
    ),
):
    """字段名 `file`；Query：`enable_word_ocr` / `enable_word_vlm_fallback` / `word_vlm_min_chars`。"""
    return await _with_convert_timeout(
        _convert_with_ext(
            file,
            forced_ext=".docx",
            allowed={".docx"},
            enable_word_ocr=enable_word_ocr,
            enable_word_vlm_fallback=enable_word_vlm_fallback,
            word_vlm_min_chars=word_vlm_min_chars,
        ),
        label="Word",
        timeout_sec=_VLM_CONVERT_TIMEOUT_SEC,
    )


# -----------------------------------------------------------------------------
# 栅格图片（PNG / JPEG / …）
# -----------------------------------------------------------------------------
@router.post(
    "/image",
    response_model=ConvertResponse,
    summary="图片转 Markdown",
    description="上传图片；依赖 PaddleOCR PP-Structure（未安装时返回说明性 Markdown）。单请求最长 5 分钟。",
)
async def convert_image(file: UploadFile = File(..., description="图片文件")):
    """
    支持扩展名：png、jpg、jpeg、tif、tiff、bmp、webp。

    PPStructure 的 ``metadata`` 可能含 numpy 等非 JSON 原生类型；为避免主线程序列化失败，
    本路由在后台线程内完成 ``convert_bytes`` + ``jsonable_encoder`` + ``json.dumps``，
    再以显式 ``Response`` 下发，``ensure_ascii=False`` + ``charset=utf-8`` 确保中文按字面输出。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="请求中缺少文件名（filename）")

    raw_name = file.filename
    suffix = Path(raw_name).suffix.lower()
    ext = suffix

    if suffix not in _IMAGE_EXTS:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件扩展名: {suffix}，允许: {sorted(_IMAGE_EXTS)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    def _image_convert_and_serialize() -> bytes:
        result = convert_bytes(ext, content, raw_name)
        payload = {
            "markdown": result.markdown,
            "metadata": jsonable_encoder(result.metadata),
            "filename": raw_name,
        }
        # ensure_ascii=False：保留中文字符；不写成 \uXXXX 转义
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    body = await _with_convert_timeout(
        asyncio.to_thread(_image_convert_and_serialize),
        label="图片",
    )
    print(body.decode("utf-8"))
    return Response(
        content=body.decode("utf-8"),
        media_type="application/json; charset=utf-8",
    )


# -----------------------------------------------------------------------------
# Excel
# -----------------------------------------------------------------------------
@router.post(
    "/excel",
    response_model=ConvertResponse,
    summary="Excel 转 Markdown",
    description="上传 .xlsx 或 .xls，按 Sheet 输出 Markdown 表格。",
)
async def convert_excel(file: UploadFile = File(..., description="Excel 文件")):
    """允许扩展名：``.xlsx``、``.xls``。"""
    return await _convert_with_ext(file, forced_ext=None, allowed=_EXCEL_EXTS)


# -----------------------------------------------------------------------------
# PowerPoint
# -----------------------------------------------------------------------------
@router.post(
    "/slides",
    response_model=ConvertResponse,
    summary="PPT/PPTX 转 Markdown",
    description=(
        "上传演示文稿，**默认走视觉版**（LibreOffice → PDF → PNG → VLM 看图），"
        "按幻灯片输出按 `## ` 切片友好的 Markdown。视觉版需要系统包 "
        "`libreoffice` / `poppler-utils` 与 `settings.MODELS.VLM.api_key`，"
        "失败时自动回退到 python-pptx 文本版。整体最长 10 分钟。"
    ),
)
async def convert_slides(
    file: UploadFile = File(..., description="PPT 或 PPTX 文件"),
    pptx_visual: bool = Query(
        True,
        description="是否启用视觉版（VLM 看图）；False 走传统 python-pptx 文本抽取",
    ),
    pptx_dpi: int = Query(
        200, ge=72, le=400, description="PDF → PNG 渲染 DPI（越高越清晰但越慢）"
    ),
):
    """
    允许扩展名：``.pptx``、``.ppt``。

    视觉版输出为**纯文本 Markdown**：每页一个 ``## <语义化标题>`` + VLM 抄录正文，
    不再嵌入 base64 图片，便于切片入库。
    """
    return await _with_convert_timeout(
        _convert_with_ext(
            file,
            forced_ext=None,
            allowed=_SLIDE_EXTS,
            pptx_visual=pptx_visual,
            pptx_dpi=pptx_dpi,
        ),
        label="PPT",
        timeout_sec=_VLM_CONVERT_TIMEOUT_SEC,
    )


# -----------------------------------------------------------------------------
# JSON
# -----------------------------------------------------------------------------
@router.post(
    "/json",
    response_model=ConvertResponse,
    summary="JSON 转 Markdown",
    description="上传 UTF-8 JSON 文件，按内容体量生成表格或标题层级 Markdown。",
)
async def convert_json(file: UploadFile = File(..., description="JSON 文件")):
    """须为 ``.json`` 后缀。"""
    return await _convert_with_ext(file, forced_ext=None, allowed={".json"})
