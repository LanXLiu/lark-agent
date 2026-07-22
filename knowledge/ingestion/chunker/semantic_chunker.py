from infrastructure.conf.yaml_config import get

from knowledge.ingestion.chunker.base import BaseChunker, ChunkResult


class SemanticChunker(BaseChunker):
    """Semantic chunker: split on topic boundaries using sentence-level analysis.

    Uses simple heuristics (heading changes, topic shifts) as a lightweight
    approximation. Can be swapped for an LLM-based splitter.
    """

    name = "semantic"

    def __init__(self) -> None:
        scfg = get("chunker", {}).get("strategies", {}).get("semantic", {})
        self.min_chunk_size = scfg.get("min_chunk_size", 200)
        self.max_chunk_size = scfg.get("max_chunk_size", 800)
        self.buffer_size = scfg.get("buffer_size", 5)

    async def chunk(self, text: str, **kwargs) -> list[ChunkResult]:
        min_size = kwargs.get("min_chunk_size", self.min_chunk_size)
        max_size = kwargs.get("max_chunk_size", self.max_chunk_size)
        buffer_n = kwargs.get("buffer_size", self.buffer_size)

        lines = text.split("\n")
        chunks: list[ChunkResult] = []
        buffer: list[str] = []
        buf_len = 0
        idx = 0

        for line in lines:
            buffer.append(line)
            buf_len += len(line) + 1  # +1 for newline

            is_heading = line.startswith("#")
            is_over_max = buf_len >= max_size
            is_long_enough = buf_len >= min_size

            if (is_heading and is_long_enough) or is_over_max:
                chunk_text = "\n".join(buffer).strip()
                if chunk_text:
                    chunks.append(ChunkResult(text=chunk_text, index=idx, token_count=buf_len))
                    idx += 1
                # Keep trailing buffer_n lines for overlap
                keep = max(0, len(buffer) - buffer_n)
                buffer = buffer[keep:]
                buf_len = sum(len(l) + 1 for l in buffer)

        # Flush remaining buffer
        if buffer:
            chunk_text = "\n".join(buffer).strip()
            if chunk_text:
                chunks.append(ChunkResult(text=chunk_text, index=idx, token_count=buf_len))

        return chunks
