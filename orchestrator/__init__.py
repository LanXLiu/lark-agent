"""
编排层入口。

- ``KnowledgeBasePipeline`` / ``PipelineStats``：全量「遍历 → 转换 → 回写 → 切片」三态管线；
  常量 ``STATUS_RAW`` / ``STATUS_MARKDOWN`` / ``STATUS_CHUNK`` 用于审计 / 下游消费。
- ``PipelineStageContext`` / ``RawToMarkdownStage`` / ``MarkdownToChunkStage`` /
  ``ChunkToQdrantStage`` / ``PipelineStageOrchestrator``：可被外部编排工具逐阶段调用的拆分版管线。
"""

__all__ = [
    "KnowledgeBasePipeline",
    "PipelineStats",
    "STATUS_RAW",
    "STATUS_MARKDOWN",
    "STATUS_CHUNK",
    "STATUS_VECTORIZED",
    "PipelineStageContext",
    "StageResult",
    "RawToMarkdownStage",
    "MarkdownToChunkStage",
    "ChunkToQdrantStage",
    "PipelineStageOrchestrator",
]


def __getattr__(name: str):
    """Lazy exports keep direct script execution from tripping package imports."""
    if name in {
        "KnowledgeBasePipeline",
        "PipelineStats",
        "STATUS_RAW",
        "STATUS_MARKDOWN",
        "STATUS_CHUNK",
        "STATUS_VECTORIZED",
    }:
        if name == "STATUS_VECTORIZED":
            from .pipeline_common import STATUS_VECTORIZED

            return STATUS_VECTORIZED
        from . import knowledge_pipeline

        return getattr(knowledge_pipeline, name)

    if name in {"PipelineStageContext", "StageResult"}:
        from . import pipeline_common

        return getattr(pipeline_common, name)

    if name == "RawToMarkdownStage":
        from .raw_to_markdown import RawToMarkdownStage

        return RawToMarkdownStage

    if name == "MarkdownToChunkStage":
        from .markdown_to_chunk import MarkdownToChunkStage

        return MarkdownToChunkStage

    if name == "ChunkToQdrantStage":
        from .chunk_to_qdrant import ChunkToQdrantStage

        return ChunkToQdrantStage

    if name == "PipelineStageOrchestrator":
        from .pipeline_stages import PipelineStageOrchestrator

        return PipelineStageOrchestrator

    raise AttributeError(f"module 'orchestrator' has no attribute {name!r}")
