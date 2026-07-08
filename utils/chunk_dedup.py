"""Post-process chunk lists to remove exact and low-value duplicate chunks."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import replace

from chunker.base import ChunkResult

logger = logging.getLogger(__name__)


_MARKDOWN_ESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>])")
_WHITESPACE_RE = re.compile(r"\s+")
_HEADING_ONLY_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def normalize_chunk_text(text: str) -> str:
    """Normalize chunk text for deduplication only."""
    text = (text or "").strip()
    text = _MARKDOWN_ESCAPE_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def chunk_text_hash(text: str) -> str:
    normalized = normalize_chunk_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def deduplicate_chunks(
    chunks: list[ChunkResult],
    *,
    short_text_max_chars: int = 30,
) -> list[ChunkResult]:
    """Remove duplicate and low-value heading-only chunks.

    Rules:
    1. Exact normalized text duplicates keep the first occurrence.
    2. Heading-only / very short chunks are dropped if a later chunk has the same
       title or starts with the same heading.
    3. Very short chunks are dropped if their normalized text is contained in a
       later, longer chunk.
    """
    if not chunks:
        return []

    seen_hashes: set[str] = set()
    kept: list[ChunkResult] = []

    for idx, chunk in enumerate(chunks):
        normalized = normalize_chunk_text(chunk.text)
        if not normalized:
            continue

        digest = chunk_text_hash(chunk.text)
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)

        if _should_drop_short_or_heading_chunk(
            chunk,
            chunks[idx + 1 :],
            normalized,
            short_text_max_chars,
        ):
            continue

        kept.append(chunk)

    return _reindex_chunks(kept)


def deduplicate_document_chunks(
    chunks: list[ChunkResult],
    *,
    short_text_max_chars: int = 30,
    enable_lsh: bool = True,
    lsh_threshold: float = 0.9,
    lsh_min_chars: int = 80,
    lsh_same_title_only: bool = True,
) -> list[ChunkResult]:
    """Apply all in-document chunk deduplication rules.

    Order matters:
    1. deterministic exact/title/containment dedup;
    2. conservative LSH near-duplicate dedup within the same document.
    """
    deduped = deduplicate_chunks(
        chunks,
        short_text_max_chars=short_text_max_chars,
    )
    if not enable_lsh or len(deduped) <= 1:
        return deduped

    try:
        from utils.lsh_deduplication import deduplicate_chunks_with_lsh
    except ImportError as exc:
        logger.warning("LSH chunk dedup skipped because dependencies are missing: %s", exc)
        return deduped

    return deduplicate_chunks_with_lsh(
        deduped,
        threshold=lsh_threshold,
        min_chars=lsh_min_chars,
        same_title_only=lsh_same_title_only,
    )


def _should_drop_short_or_heading_chunk(
    chunk: ChunkResult,
    later_chunks: list[ChunkResult],
    normalized: str,
    short_text_max_chars: int,
) -> bool:
    title = str(chunk.metadata.get("title") or "").strip()
    heading_title = _heading_only_title(chunk.text)
    is_heading_only = heading_title is not None
    is_short = len(normalized) < short_text_max_chars

    if not is_heading_only and not is_short:
        return False

    candidate_title = title or heading_title or normalized.lstrip("#").strip()
    candidate_heading = f"## {candidate_title}" if candidate_title else ""

    for later in later_chunks:
        later_normalized = normalize_chunk_text(later.text)
        if not later_normalized:
            continue

        later_title = str(later.metadata.get("title") or "").strip()
        if candidate_title and later_title == candidate_title:
            return True

        if candidate_heading and later_normalized.startswith(candidate_heading):
            return True

        if (
            is_short
            and len(later_normalized) > len(normalized)
            and normalized in later_normalized
        ):
            return True

    return False


def _heading_only_title(text: str) -> str | None:
    normalized_lines = [line.strip() for line in (text or "").strip().splitlines() if line.strip()]
    if len(normalized_lines) != 1:
        return None
    match = _HEADING_ONLY_RE.match(normalized_lines[0])
    return match.group(1).strip() if match else None


def _reindex_chunks(chunks: list[ChunkResult]) -> list[ChunkResult]:
    return [
        replace(chunk, index=new_index, token_count=len(chunk.text))
        for new_index, chunk in enumerate(chunks)
    ]
