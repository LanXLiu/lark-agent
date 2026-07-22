"""Coroutine orchestration for split pipeline stages.

- ``process_one_file``：raw / markdown / chunk / 全流程（不含单独向量化）
- ``process_one_file_chunk_to_qdrant``：单独 chunk -> Qdrant
- ``main()`` / ``main_chunk_to_qdrant()``：批量入口

命令行::

    python -m knowledge.ingestion.orchestrator.pipeline_stages                 # 全流程默认
    python -m knowledge.ingestion.orchestrator.pipeline_stages chunk_to_qdrant # 仅向量化
    python -m knowledge.ingestion.orchestrator.pipeline_stages chunk_to_qdrant --force
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from botocore.exceptions import ClientError

# Allow direct execution with ``python -m knowledge.ingestion.orchestrator.pipeline_stages``.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_METADATA_DIR = Path(__file__).resolve().parent / "metadata"
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from loguru import logger

from knowledge.ingestion.orchestrator.chunk_to_qdrant import ChunkToQdrantStage
from knowledge.ingestion.orchestrator.markdown_to_chunk import MarkdownToChunkStage
from knowledge.ingestion.orchestrator.pipeline_common import PipelineStageContext, StageResult
from knowledge.ingestion.orchestrator.raw_to_markdown import RawToMarkdownStage
from knowledge.utils.sparse_embedder import ensure_fastembed_installed


class PipelineStageOrchestrator:
    """Compose raw -> markdown -> chunk -> Qdrant stages."""

    def __init__(
        self,
        context: PipelineStageContext | None = None,
        *,
        raw_to_markdown: RawToMarkdownStage | None = None,
        markdown_to_chunk: MarkdownToChunkStage | None = None,
        chunk_to_qdrant: ChunkToQdrantStage | None = None,
    ) -> None:
        self.context = context or PipelineStageContext()
        self.raw_to_markdown_stage = raw_to_markdown or RawToMarkdownStage(self.context)
        self.markdown_to_chunk_stage = markdown_to_chunk or MarkdownToChunkStage(self.context)
        self.chunk_to_qdrant_stage = chunk_to_qdrant or ChunkToQdrantStage(self.context)

    async def raw_to_markdown(self, raw_key: str) -> StageResult:
        return await self.raw_to_markdown_stage.run(raw_key)

    async def markdown_to_chunk(
        self,
        raw_key: str,
        *,
        markdown_key: str | None = None,
        converter: str = "unknown",
    ) -> StageResult:
        return await self.markdown_to_chunk_stage.run(
            raw_key,
            markdown_key=markdown_key,
            converter=converter,
        )

    async def raw_to_markdown_and_chunk(self, raw_key: str) -> StageResult:
        """Run raw -> Markdown first, then Markdown -> chunk for the same source object."""
        md_result = await self.raw_to_markdown(raw_key)
        chunk_result = await self.markdown_to_chunk(
            raw_key,
            markdown_key=md_result.markdown_key,
            converter=md_result.converter,
        )
        chunk_result.stage = "raw_to_markdown_and_chunk"
        return chunk_result

    async def chunk_to_qdrant(
        self,
        raw_key: str,
        *,
        chunk_key: str | None = None,
        collection: str | None = None,
        tenant_id: str | None = None,
        tags: list[str] | None = None,
    ) -> StageResult:
        return await self.chunk_to_qdrant_stage.run(
            raw_key,
            chunk_key=chunk_key,
            collection=collection,
            tenant_id=tenant_id,
            tags=tags,
        )

    async def raw_to_markdown_and_chunk_and_qdrant(self, raw_key: str) -> StageResult:
        chunk_result = await self.raw_to_markdown_and_chunk(raw_key)
        qdrant_result = await self.chunk_to_qdrant(
            raw_key,
            chunk_key=chunk_result.chunk_key,
        )
        qdrant_result.stage = "raw_to_markdown_and_chunk_and_qdrant"
        return qdrant_result


def create_default_orchestrator() -> PipelineStageOrchestrator:
    """构建带默认配置的编排器（main / main_chunk_to_qdrant 共用）。"""
    context = PipelineStageContext(
        raw_to_markdown_metadata_path=_METADATA_DIR / "raw_to_markdown_metadata.jsonl",
        markdown_to_chunk_metadata_path=_METADATA_DIR / "markdown_to_chunk_metadata.jsonl",
        chunk_to_qdrant_metadata_path=_METADATA_DIR / "chunk_to_qdrant_metadata.jsonl",
        source_prefix=PipelineStageContext.default_source_prefix(),
        markdown_prefix=PipelineStageContext.DEFAULT_MARKDOWN_PREFIX,
        chunk_prefix=PipelineStageContext.DEFAULT_CHUNK_PREFIX,
    )
    return PipelineStageOrchestrator(
        context=context,
        raw_to_markdown=RawToMarkdownStage(
            context,
            pptx_visual=True,
            pptx_dpi=200,
            enable_word_vlm_fallback=True,
        ),
        markdown_to_chunk=MarkdownToChunkStage(
            context,
            chunk_strategy=None,
            chunk_max_chars=1500,
            chunk_overlap_chars=100,
        ),
        chunk_to_qdrant=ChunkToQdrantStage(context),
    )


async def main() -> None:
    """批量执行 raw -> markdown -> chunk -> Qdrant（或按 process_one_file 内注释切换阶段）。"""
    orchestrator = create_default_orchestrator()
    context = orchestrator.context

    raw_keys = context.list_source_keys()
    if not raw_keys:
        logger.warning(
            "MinIO bucket={} 下没有 {} 源文件",
            context.BUCKET,
            context.source_prefix,
        )
        return

    logger.info("全流程模式：prefix={} 发现 raw 文件 {} 个", context.source_prefix, len(raw_keys))
    for raw_key in raw_keys:
        await process_one_file(orchestrator, raw_key)


async def main_chunk_to_qdrant(*, force: bool = False) -> None:
    """批量执行 chunk -> Qdrant（仅处理已有 chunk、尚未向量化的文件）。"""
    ensure_fastembed_installed()
    orchestrator = create_default_orchestrator()
    context = orchestrator.context

    raw_keys = context.list_source_keys()
    if not raw_keys:
        logger.warning(
            "MinIO bucket={} 下没有 {} 源文件",
            context.BUCKET,
            context.source_prefix,
        )
        return

    if force:
        logger.info("chunk->Qdrant 强制模式：将覆盖已有向量（--force）")
    logger.info("chunk->Qdrant 模式：prefix={} 发现 raw 文件 {} 个", context.source_prefix, len(raw_keys))
    for raw_key in raw_keys:
        await process_one_file_chunk_to_qdrant(orchestrator, raw_key, force=force)


async def process_one_file_chunk_to_qdrant(
    orchestrator: PipelineStageOrchestrator,
    raw_key: str,
    *,
    chunk_key: str | None = None,
    collection: str | None = None,
    tenant_id: str | None = None,
    tags: list[str] | None = None,
    force: bool = False,
) -> StageResult | None:
    """单独执行 chunk -> Qdrant（与 process_one_file 解耦，供补向量或批量入库使用）。"""
    context = orchestrator.context
    try:
        if not force and context.has_vectorized_record(raw_key):
            logger.info("已向量化，跳过 chunk->Qdrant key={}（重跑请加 --force）", raw_key)
            return None

        effective_chunk_key = chunk_key or context.get_chunk_key(raw_key)
        if not effective_chunk_key:
            logger.warning("无 chunk 元数据，跳过 chunk->Qdrant key={}", raw_key)
            return None

        result = await orchestrator.chunk_to_qdrant(
            raw_key,
            chunk_key=effective_chunk_key,
            collection=collection,
            tenant_id=tenant_id,
            tags=tags,
        )
    except ClientError as e:
        logger.error("MinIO 访问失败 key={} error={}", raw_key, e)
        return None
    except Exception as e:
        logger.exception("chunk->Qdrant 失败 key={} error={}", raw_key, e)
        return None

    logger.info(
        "chunk->Qdrant 完成 key={} collection={} points={}",
        raw_key,
        result.qdrant_collection,
        result.chunk_count,
    )
    return result


async def process_one_file(orchestrator: PipelineStageOrchestrator, raw_key: str) -> None:
    """单文件：raw / markdown / chunk / 全流程（不含 chunk->Qdrant，向量化请用 process_one_file_chunk_to_qdrant）。"""
    try:
        context = orchestrator.context

        if context.has_chunk_record(raw_key):
            if context.has_vectorized_record(raw_key):
                logger.info("已存在向量化元数据，跳过 key={}", raw_key)
                return
            logger.info("已存在 chunk 元数据，继续执行 chunk->Qdrant key={}", raw_key)
            result = await orchestrator.chunk_to_qdrant(
                raw_key,
                chunk_key=context.get_chunk_key(raw_key),
            )
            logger.info("单文件处理完成 key={} result={}", raw_key, result)
            return

        if context.has_markdown_record(raw_key):
            logger.info("已存在 markdown 元数据，跳过 raw->md，仅执行切片 key={}", raw_key)
            chunk_result = await orchestrator.markdown_to_chunk(
                raw_key,
                markdown_key=context.get_markdown_key(raw_key),
                converter=context.get_converter(raw_key),
            )
            result = await orchestrator.chunk_to_qdrant(
                raw_key,
                chunk_key=chunk_result.chunk_key,
            )
            logger.info("单文件处理完成 key={} result={}", raw_key, result)
            return

        # 1) 单独 raw -> markdown 层
        # result = await orchestrator.raw_to_markdown(raw_key)

        # 2) 单独 markdown -> chunk 层
        # result = await orchestrator.markdown_to_chunk(raw_key)

        # 3) raw -> markdown -> chunk
        # result = await orchestrator.raw_to_markdown_and_chunk(raw_key)

        # 4) raw -> markdown -> chunk -> Qdrant 全流程
        result = await orchestrator.raw_to_markdown_and_chunk_and_qdrant(raw_key)
    except ClientError as e:
        logger.error("MinIO 访问失败 key={} error={}", raw_key, e)
        return
    except Exception as e:
        logger.exception("处理失败 key={} error={}", raw_key, e)
        return

    logger.info("单文件处理完成 key={} result={}", raw_key, result)


if __name__ == "__main__":
    argv = sys.argv[1:]
    mode = "full"
    force = False
    if argv and argv[0] == "chunk_to_qdrant":
        mode = argv.pop(0)
    if "--force" in argv:
        force = True
        argv.remove("--force")
    if argv and argv[0] not in {"chunk_to_qdrant", "--force"}:
        mode = argv[0].strip()

    if mode == "chunk_to_qdrant":
        asyncio.run(main_chunk_to_qdrant(force=force))
    else:
        asyncio.run(main())
