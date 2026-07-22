"""Public entrypoints for the knowledge ingestion pipeline."""

__all__ = ["DEFAULT_SUPPORTED_EXTS", "KnowledgeBasePipeline", "PipelineStats"]


def __getattr__(name: str):
    if name in __all__:
        from knowledge.ingestion.orchestrator import knowledge_pipeline

        return getattr(knowledge_pipeline, name)
    raise AttributeError(f"module 'knowledge.ingestion' has no attribute {name!r}")
