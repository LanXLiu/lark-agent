from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkResult:
    text: str
    index: int
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseChunker(ABC):
    """Base class for text chunking strategies."""

    name: str = "base"

    @abstractmethod
    async def chunk(self, text: str, **kwargs) -> list[ChunkResult]:
        """Split text into chunks.

        Args:
            text: The markdown text to chunk.
            **kwargs: Strategy-specific parameters.

        Returns:
            List of ChunkResult objects.
        """
        ...
