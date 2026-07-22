"""Markdown -> chunk JSON stage."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from loguru import logger

from knowledge.ingestion.chunker import ChunkResult, ChunkerFactory
from knowledge.ingestion.orchestrator.pipeline_common import PipelineStageContext, StageResult
from knowledge.utils.chunk_dedup import deduplicate_document_chunks


class MarkdownToChunkStage:
    """Chunk an existing Markdown object and persist chunk JSON + metadata."""

    def __init__(
        self,
        context: PipelineStageContext,
        *,
        chunk_strategy: str | None = None,
        chunk_max_chars: int = 1500,
        chunk_overlap_chars: int = 100,
    ) -> None:
        self.context = context
        self.chunk_max_chars = int(chunk_max_chars)
        self.chunk_overlap_chars = int(chunk_overlap_chars)
        self.chunker = ChunkerFactory.create(chunk_strategy)

    async def run(
        self,
        raw_key: str,
        *,
        markdown_key: str | None = None,
        converter: str = "unknown",
    ) -> StageResult:
        return await asyncio.to_thread(
            self._run_sync,
            raw_key,
            markdown_key,
            converter,
        )

    def _run_sync(
        self,
        raw_key: str,
        markdown_key: str | None,
        converter: str,
    ) -> StageResult:
        obj = self.context.stat_source_object(raw_key)
        markdown_rec = self.context.raw_to_markdown_index.get(raw_key)
        if markdown_key is None and not markdown_rec:
            raise RuntimeError(
                f"raw_to_markdown metadata not found for {raw_key}; skip markdown_to_chunk"
            )

        md_key = (
            markdown_key
            or markdown_rec.get("markdown_key")
            or self.context.build_markdown_key(raw_key)
        )
        md_text = self.context.download_markdown(md_key)
        if not converter or converter == "unknown":
            converter = self.context.raw_to_markdown_index.get(raw_key, {}).get(
                "converter",
                "unknown",
            )

        file_ext = Path(raw_key).suffix.lower()
        chunks = self.run_chunker(md_text, file_ext)
        before_dedup = len(chunks)
        chunks = deduplicate_document_chunks(chunks)
        if len(chunks) != before_dedup:
            logger.info(
                "chunk 去重完成 key={} before={} after={}",
                raw_key,
                before_dedup,
                len(chunks),
            )
        chunk_key = self.context.build_chunk_key(raw_key)
        payload_bytes = self.build_payload(
            raw_key=raw_key,
            obj=obj,
            md_key=md_key,
            md_text=md_text,
            chunks=chunks,
            converter=converter,
        )
        self.context.upload_chunk_json(chunk_key, payload_bytes)
        self.context.record_chunk(
            obj=obj,
            key=raw_key,
            md_key=md_key,
            md_chars=len(md_text),
            chunk_key=chunk_key,
            chunk_count=len(chunks),
            chunk_bytes=len(payload_bytes),
            converter=converter,
        )

        logger.info(
            "markdown_to_chunk 完成 key={} md={} -> {} | chunks={}",
            raw_key,
            md_key,
            chunk_key,
            len(chunks),
        )
        return StageResult(
            source_key=raw_key,
            stage="markdown_to_chunk",
            markdown_key=md_key,
            chunk_key=chunk_key,
            markdown_chars=len(md_text),
            chunk_count=len(chunks),
            converter=converter,
        )

    def run_chunker(self, md_text: str, file_ext: str) -> list[ChunkResult]:
        coro = self.chunker.chunk(
            md_text,
            chunk_size=self.chunk_max_chars,
            chunk_overlap=self.chunk_overlap_chars,
            file_ext=file_ext,
        )
        return asyncio.run(coro)

    def build_payload(
        self,
        *,
        raw_key: str,
        obj: dict,
        md_key: str,
        md_text: str,
        chunks: list[ChunkResult],
        converter: str,
    ) -> bytes:
        rec_base = self.context.build_metadata_record(obj)
        payload_obj = {
            "doc_uuid": rec_base["uuid"],
            "source": raw_key,
            "markdown_key": md_key,
            "filename": rec_base["filename"],
            "converter": converter,
            "chunker_strategy": getattr(self.chunker, "name", type(self.chunker).__name__),
            "chunk_count": len(chunks),
            "chunks": [
                {
                    "index": c.index,
                    "text": c.text,
                    "token_count": c.token_count,
                    "metadata": c.metadata,
                }
                for c in chunks
            ],
        }
        return json.dumps(payload_obj, ensure_ascii=False, indent=2).encode("utf-8")
