from infrastructure.conf.yaml_config import get

from knowledge.ingestion.chunker.base import BaseChunker
from knowledge.ingestion.chunker.markdown_structure_chunker import MarkdownStructureChunker
from knowledge.ingestion.chunker.recursive_chunker import RecursiveChunker
from knowledge.ingestion.chunker.semantic_chunker import SemanticChunker
from knowledge.ingestion.chunker.text_chunker import TextChunker


class ChunkerFactory:
    _registry: dict[str, type[BaseChunker]] = {
        "text": TextChunker,
        "recursive": RecursiveChunker,
        "semantic": SemanticChunker,
        "markdown_structure": MarkdownStructureChunker,
    }

    @classmethod
    def create(cls, strategy: str | None = None) -> BaseChunker:
        if strategy is None:
            strategy = get("chunker", {}).get("default_strategy", "recursive")

        cls_cls = cls._registry.get(strategy)
        if cls_cls is None:
            raise ValueError(
                f"Unknown chunker strategy: {strategy}. Available: {list(cls._registry.keys())}"
            )
        return cls_cls()
