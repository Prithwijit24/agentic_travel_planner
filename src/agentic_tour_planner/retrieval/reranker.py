from __future__ import annotations

import re
from collections import Counter

from agentic_tour_planner.domain.models import SourceDocument


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class HybridReranker:
    def rerank(
        self,
        query: str,
        documents: list[SourceDocument],
        top_k: int | None = None,
        limit: int | None = None,
    ) -> list[SourceDocument]:
        target_k = top_k if top_k is not None else limit if limit is not None else len(documents)
        scored = sorted(
            documents,
            key=lambda doc: self._lexical_overlap(query, doc.content) + float(doc.metadata.get("score", 0.0)),
            reverse=True,
        )
        return scored[:target_k]

    def _lexical_overlap(self, query: str, content: str) -> float:
        q = Counter(_tokenize(query))
        d = Counter(_tokenize(content))
        return float(sum(min(q[token], d[token]) for token in q))
