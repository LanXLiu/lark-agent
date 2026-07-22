"""Raw object -> Markdown stage."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

from knowledge.ingestion.orchestrator.pipeline_common import PipelineStageContext, StageResult


class RawToMarkdownStage:
    """Convert one raw MinIO object to Markdown and persist the stage output."""

    def __init__(
        self,
        context: PipelineStageContext,
        *,
        pptx_visual: bool = True,
        pptx_dpi: int = 200,
        enable_word_vlm_fallback: bool = True,
        word_vlm_min_chars: int = 20,
    ) -> None:
        self.context = context
        self.pptx_visual = bool(pptx_visual)
        self.pptx_dpi = int(pptx_dpi)
        self.enable_word_vlm_fallback = bool(enable_word_vlm_fallback)
        self.word_vlm_min_chars = int(word_vlm_min_chars)

    async def run(self, raw_key: str) -> StageResult:
        return await asyncio.to_thread(self._run_sync, raw_key)

    def _run_sync(self, raw_key: str) -> StageResult:
        obj = self.context.stat_source_object(raw_key)
        content = self.context.download_raw(raw_key)
        md_text, conv_meta = self.convert(content, raw_key)

        md_key = self.context.build_markdown_key(raw_key)
        self.context.upload_markdown(md_key, md_text)
        self.context.record_markdown(
            obj=obj,
            key=raw_key,
            md_key=md_key,
            md_text=md_text,
            conv_meta=conv_meta,
        )

        converter = conv_meta.get("converter") or "unknown"
        logger.info(
            "raw_to_markdown 完成 key={} -> {} | chars={} | converter={}",
            raw_key,
            md_key,
            len(md_text),
            converter,
        )
        return StageResult(
            source_key=raw_key,
            stage="raw_to_markdown",
            markdown_key=md_key,
            markdown_chars=len(md_text),
            converter=converter,
        )

    def convert(self, content: bytes, key: str) -> tuple[str, dict[str, Any]]:
        suffix = Path(key).suffix.lower()
        filename = Path(key).name

        if suffix in {".md", ".markdown"}:
            return (
                content.decode("utf-8", errors="replace"),
                {"converter": "passthrough_md", "extension": suffix},
            )
        if suffix == ".txt":
            text = content.decode("utf-8", errors="replace")
            md = f"# {Path(filename).stem}\n\n{text}\n"
            return md, {"converter": "passthrough_txt", "extension": suffix}

        from knowledge.ingestion.file_to_markdown.unified_entry import convert_bytes

        kwargs: dict[str, Any] = {}
        if suffix in {".pptx", ".ppt"}:
            kwargs["pptx_visual"] = self.pptx_visual
            kwargs["pptx_dpi"] = self.pptx_dpi
        elif suffix == ".docx":
            kwargs["enable_word_vlm_fallback"] = self.enable_word_vlm_fallback
            kwargs["word_vlm_min_chars"] = self.word_vlm_min_chars

        result = convert_bytes(suffix, content, filename, **kwargs)
        return result.markdown, result.metadata
