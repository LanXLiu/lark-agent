from chunker.base import BaseChunker, ChunkResult


class TextChunker(BaseChunker):
    """Simple text chunker: split by paragraph boundaries."""

    name = "text"

    async def chunk(self, text: str, **kwargs) -> list[ChunkResult]:
        max_chars = kwargs.get("chunk_size", 512)
        paragraphs = text.split("\n\n")
        chunks: list[ChunkResult] = []
        buffer: list[str] = []
        buf_len = 0
        idx = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            para_len = len(para)
            if buf_len + para_len > max_chars and buffer:
                text_block = "\n\n".join(buffer)
                chunks.append(ChunkResult(text=text_block, index=idx, token_count=buf_len))
                idx += 1
                buffer = [para]
                buf_len = para_len
            else:
                buffer.append(para)
                buf_len += para_len

        if buffer:
            text_block = "\n\n".join(buffer)
            chunks.append(ChunkResult(text=text_block, index=idx, token_count=buf_len))

        return chunks
