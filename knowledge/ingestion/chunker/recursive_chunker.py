from infrastructure.conf.yaml_config import get

from knowledge.ingestion.chunker.base import BaseChunker, ChunkResult


class RecursiveChunker(BaseChunker):
    """Recursive chunker: try separators in order and split recursively."""

    name = "recursive"

    def __init__(self) -> None:
        rcfg = get("chunker", {}).get("strategies", {}).get("recursive", {})
        self.chunk_size = rcfg.get("chunk_size", 512)
        self.chunk_overlap = rcfg.get("chunk_overlap", 128)
        self.separators = rcfg.get(
            "separators",
            ["\n\n", "\n", "。", ".", " ", ""],
        )

    async def chunk(self, text: str, **kwargs) -> list[ChunkResult]:
        chunk_size = kwargs.get("chunk_size", self.chunk_size)
        chunk_overlap = kwargs.get("chunk_overlap", self.chunk_overlap)
        separators = kwargs.get("separators", self.separators)

        return self._recursive_split(text, separators, chunk_size, chunk_overlap)

    def _recursive_split(
        self,
        text: str,
        separators: list[str],
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[ChunkResult]:
        if not separators:
            return [ChunkResult(text=text, index=0, token_count=len(text))]

        sep = separators[0]
        remaining_seps = separators[1:]

        if sep == "":
            # Character-level split
            chunks: list[ChunkResult] = []
            start = 0
            idx = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunk_text = text[start:end]
                chunks.append(ChunkResult(text=chunk_text, index=idx, token_count=len(chunk_text)))
                idx += 1
                start += chunk_size - chunk_overlap
            return chunks

        # Split by current separator
        segments = text.split(sep)
        merged: list[str] = []
        current = ""

        for seg in segments:
            if not seg:
                continue
            candidate = seg if not current else current + sep + seg
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    merged.append(current)
                if len(seg) > chunk_size:
                    # Recursively split oversized segment with remaining separators
                    sub_chunks = self._recursive_split(seg, remaining_seps, chunk_size, chunk_overlap)
                    for sc in sub_chunks:
                        merged.append(sc.text)
                    current = ""
                else:
                    current = seg

        if current:
            merged.append(current)

        # Build overlap-aware chunks
        result: list[ChunkResult] = []
        idx = 0
        for i, m in enumerate(merged):
            # If this segment is still too large, recursive split at char level
            if len(m) > chunk_size and remaining_seps:
                sub = self._recursive_split(m, remaining_seps, chunk_size, chunk_overlap)
                for sc in sub:
                    result.append(ChunkResult(text=sc.text, index=idx, token_count=len(sc.text)))
                    idx += 1
            else:
                result.append(ChunkResult(text=m, index=idx, token_count=len(m)))
                idx += 1

        return result
