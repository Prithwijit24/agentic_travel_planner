from __future__ import annotations

import re
from collections import Counter

from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def _tokenize(text: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def _lexical_score(query: str, content: str) -> float:
    q = _tokenize(query)
    d = _tokenize(content)
    return float(sum(min(q[tok], d[tok]) for tok in q))


def rerank_documents(
    query: str,
    documents: list[SourceDocument],
    top_k: int | None = None,
    limit: int | None = None,
) -> list[SourceDocument]:
    target_k = top_k if top_k is not None else limit if limit is not None else len(documents)
    logger.info("rerank_documents: {} documents target_k={} query_len={}", len(documents), target_k, len(query))
    scored = sorted(
        documents,
        key=lambda doc: _lexical_score(query, doc.content) + float(doc.metadata.get("score", 0.0)),
        reverse=True,
    )
    result = scored[:target_k]
    logger.debug("rerank_documents: returning {} documents", len(result))
    return result
