"""Unified retrieval pipeline with graceful fallback.

Chains graph retrieval → vector filter → enrich.
Falls back to API when Neo4j or ChromaDB are unavailable.
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from agentic_tour_planner.retrieval import graph_retrieval, vector_retrieval, api_retrieval


def _try_primary_else_fallback(primary_fn, fallback_fn, *args, **kwargs):
    """Try primary function, fall back to fallback function on failure."""
    try:
        result = primary_fn(*args, **kwargs)
        if result:  # Primary returned meaningful result
            return result
    except Exception as e:
        logger.warning(f"Primary retrieval failed, falling back: {e}")
    return fallback_fn(*args, **kwargs)


def retrieve(
    destination: str,
    interest_tags: list[str] | None = None,
    top_k: int = 40,
) -> list[dict[str, Any]]:
    """Main retrieval entry point. Returns enriched POI records."""
    start = time.time()
    interest_tags = interest_tags or []

    # 1. Get candidates
    graph_client = graph_retrieval.get_graph_db_or_none()
    if graph_client:
        poi_ids = graph_retrieval.get_candidates(destination, graph_client)
        enrich_fn = lambda ids: graph_retrieval.enrich(ids, graph_client)
    else:
        logger.info("Using API fallback for candidate retrieval")
        poi_ids = api_retrieval.get_candidates(destination)
        enrich_fn = api_retrieval.enrich

    if not poi_ids:
        logger.warning(f"No candidates found for '{destination}'")
        return []

    # 2. Filter by interest
    vector_client = vector_retrieval.get_vector_db_or_none()
    if vector_client and interest_tags:
        filtered = vector_retrieval.filter_by_interest(poi_ids, interest_tags, vector_client, top_k=top_k)
    elif interest_tags:
        filtered = api_retrieval.filter_by_interest(poi_ids, interest_tags, top_k)
    else:
        filtered = poi_ids[:top_k]

    # 3. Enrich
    results = enrich_fn(filtered)

    elapsed = time.time() - start
    logger.info(f"Retrieved {len(results)} POIs for '{destination}' in {elapsed:.2f}s")
    return results


def get_available_tags(destination: str, limit: int = 10) -> list[str]:
    """Get dynamic interest tags for a destination."""
    graph_client = graph_retrieval.get_graph_db_or_none()
    if graph_client:
        return graph_retrieval.get_available_tags(destination, graph_client, limit)
    return api_retrieval.get_available_tags(destination, limit)


def get_balanced_default_pois(destination: str, limit_per_category: int = 3) -> list[str]:
    """Get balanced POI selection when no interests specified."""
    graph_client = graph_retrieval.get_graph_db_or_none()
    if graph_client:
        return graph_retrieval.get_balanced_default_pois(destination, graph_client, limit_per_category)
    return api_retrieval.get_balanced_default_pois(destination, limit_per_category)
