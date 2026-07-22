from __future__ import annotations

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.retrieval.graph_store import create_graph_store
from agentic_tour_planner.retrieval.vector_store import VectorStore
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


HYBRID_STRATEGIES = {
    "vector_only",
    "graph_only",
    "rrf",
    "weighted_sum",
    "vector_first",
    "graph_first",
}


class HybridRetriever:
    def __init__(self, vector_store=None, graph_store=None) -> None:
        self.settings = get_settings()
        self.vector_store = vector_store or VectorStore()
        self.graph_store = graph_store or create_graph_store()
        logger.debug("HybridRetriever initialized")

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        *,
        strategy: str | None = None,
        graph_method: str | None = None,
    ) -> list[SourceDocument]:
        target_k = top_k or self.settings.retrieval_top_k
        resolved_strategy = strategy or getattr(self.settings, "hybrid_retrieval_strategy", "rrf")
        resolved_graph_method = graph_method or getattr(self.settings, "graph_retrieval_method", "graph_hierarchy")
        logger.info("HybridRetriever.retrieve: strategy={} graph_method={} top_k={} query_len={}", resolved_strategy, resolved_graph_method, target_k, len(query))
        if resolved_strategy not in HYBRID_STRATEGIES:
            raise ValueError(f"Unsupported hybrid retrieval strategy: {resolved_strategy}")

        vector_docs = []
        graph_docs = []
        if resolved_strategy != "graph_only":
            vector_docs = self.vector_store.retrieve(query=query, top_k=target_k)
        if resolved_strategy != "vector_only":
            graph_top_k = int(getattr(self.settings, "graph_retrieval_top_k", target_k))
            graph_docs = self.graph_store.retrieve(query=query, top_k=graph_top_k, method=resolved_graph_method)

        logger.debug("HybridRetriever.retrieve: vector_docs={} graph_docs={}", len(vector_docs), len(graph_docs))
        if resolved_strategy == "vector_only":
            return [_mark_source(doc, "vector") for doc in vector_docs[:target_k]]
        if resolved_strategy == "graph_only":
            return graph_docs[:target_k]
        if resolved_strategy == "weighted_sum":
            return self._weighted_sum(vector_docs, graph_docs, target_k)
        if resolved_strategy == "vector_first":
            return self._ordered_merge(vector_docs, graph_docs, target_k, primary="vector")
        if resolved_strategy == "graph_first":
            return self._ordered_merge(graph_docs, vector_docs, target_k, primary="graph")
        result = self._rrf(vector_docs, graph_docs, target_k)
        logger.debug("HybridRetriever.retrieve: returning {} documents", len(result))
        return result

    def _rrf(
        self,
        vector_docs: list[SourceDocument],
        graph_docs: list[SourceDocument],
        top_k: int,
    ) -> list[SourceDocument]:
        logger.debug("HybridRetriever._rrf: vector={} graph={} top_k={}", len(vector_docs), len(graph_docs), top_k)
        k = float(getattr(self.settings, "rrf_k", 60))
        scores: dict[str, float] = {}
        docs_by_id: dict[str, SourceDocument] = {}
        graph_metadata: dict[str, dict] = {}
        for rank, doc in enumerate(vector_docs, start=1):
            scores[doc.source_id] = scores.get(doc.source_id, 0.0) + 1.0 / (k + rank)
            docs_by_id.setdefault(doc.source_id, _mark_source(doc, "vector"))
        for rank, doc in enumerate(graph_docs, start=1):
            scores[doc.source_id] = scores.get(doc.source_id, 0.0) + 1.0 / (k + rank)
            docs_by_id.setdefault(doc.source_id, doc)
            graph_metadata[doc.source_id] = doc.metadata
        return [
            _mark_hybrid(docs_by_id[source_id], score, graph_metadata.get(source_id))
            for source_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        ]

    def _weighted_sum(
        self,
        vector_docs: list[SourceDocument],
        graph_docs: list[SourceDocument],
        top_k: int,
    ) -> list[SourceDocument]:
        logger.debug("HybridRetriever._weighted_sum: vector={} graph={} top_k={}", len(vector_docs), len(graph_docs), top_k)
        vector_weight = float(getattr(self.settings, "hybrid_vector_weight", 0.6))
        graph_weight = float(getattr(self.settings, "hybrid_graph_weight", 0.4))
        vector_scores = _normalized_scores(vector_docs, "score")
        graph_scores = _normalized_scores(graph_docs, "graph_score")
        docs_by_id = {doc.source_id: _mark_source(doc, "vector") for doc in vector_docs}
        docs_by_id.update({doc.source_id: doc for doc in graph_docs})
        scores = {
            source_id: vector_weight * vector_scores.get(source_id, 0.0) + graph_weight * graph_scores.get(source_id, 0.0)
            for source_id in set(vector_scores) | set(graph_scores)
        }
        graph_metadata = {doc.source_id: doc.metadata for doc in graph_docs}
        return [
            _mark_hybrid(docs_by_id[source_id], score, graph_metadata.get(source_id))
            for source_id, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        ]

    @staticmethod
    def _ordered_merge(
        primary_docs: list[SourceDocument],
        secondary_docs: list[SourceDocument],
        top_k: int,
        *,
        primary: str,
    ) -> list[SourceDocument]:
        logger.debug("HybridRetriever._ordered_merge: primary={} primary_docs={} secondary={} top_k={}", primary, len(primary_docs), len(secondary_docs), top_k)
        seen = set()
        merged: list[SourceDocument] = []
        for doc in [*primary_docs, *secondary_docs]:
            if doc.source_id in seen:
                continue
            seen.add(doc.source_id)
            merged.append(_mark_source(doc, primary if len(merged) < len(primary_docs) else "hybrid"))
            if len(merged) >= top_k:
                break
        return merged


def _normalized_scores(documents: list[SourceDocument], key: str) -> dict[str, float]:
    raw = {doc.source_id: float(doc.metadata.get(key, doc.metadata.get("score", 0.0)) or 0.0) for doc in documents}
    if not raw:
        return {}
    max_score = max(raw.values()) or 1.0
    return {source_id: score / max_score for source_id, score in raw.items()}


def _mark_source(document: SourceDocument, source: str) -> SourceDocument:
    return SourceDocument(
        source_id=document.source_id,
        source_type=document.source_type,
        title=document.title,
        url=document.url,
        content=document.content,
        metadata={**document.metadata, "retrieval_source": source},
    )


def _mark_hybrid(document: SourceDocument, score: float, graph_metadata: dict | None = None) -> SourceDocument:
    metadata = {**document.metadata, **(graph_metadata or {})}
    return SourceDocument(
        source_id=document.source_id,
        source_type=document.source_type,
        title=document.title,
        url=document.url,
        content=document.content,
        metadata={**metadata, "score": score, "hybrid_score": score, "retrieval_source": "hybrid"},
    )
