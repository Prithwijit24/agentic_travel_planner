from __future__ import annotations

from collections.abc import Iterable

from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def chunk_text(text: str, chunk_size: int, overlap: int) -> Iterable[str]:
    logger.debug("chunk_text: chunk_size={} overlap={} input_len={}", chunk_size, overlap, len(text or ""))
    normalized = " ".join(text.split())
    if not normalized:
        logger.debug("chunk_text: empty input, returning no chunks")
        return []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunks.append(normalized[start:end])
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)
    logger.debug("chunk_text: produced {} chunks", len(chunks))
    return chunks
