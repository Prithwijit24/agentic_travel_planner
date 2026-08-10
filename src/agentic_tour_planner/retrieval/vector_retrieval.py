"""Vector-based retrieval from ChromaDB.

Provides interest-based filtering of POI candidates using embeddings.
"""

from __future__ import annotations

from loguru import logger

from agentic_tour_planner.vectordb.client import VectorDBClient, get_vector_db


def get_vector_db_or_none() -> VectorDBClient | None:
    """Return the vector DB client, or None if unreachable."""
    try:
        return get_vector_db()
    except Exception as e:
        logger.warning(f"ChromaDB unavailable: {e}")
        return None


def filter_by_interest(
    poi_ids: list[str],
    interest_tags: list[str],
    client: VectorDBClient,
    top_k: int = 40,
) -> list[str]:
    """Filter POIs by interest tags using vector similarity."""
    if not poi_ids or not interest_tags:
        return poi_ids

    query_text = " ".join(interest_tags)
    collection = client.get_collection()

    # Query with metadata filter to restrict to candidates
    where_filter = {"poi_id": {"$in": poi_ids}} if len(poi_ids) <= 1000 else None

    try:
        result = collection.query(
            query_texts=[query_text],
            n_results=min(top_k, len(poi_ids)),
            where=where_filter,
        )
        if result["ids"] and result["ids"][0]:
            filtered = result["ids"][0]
            logger.info(f"Vector filter: {len(poi_ids)} candidates → {len(filtered)} for tags {interest_tags}")
            return filtered
    except Exception as e:
        logger.warning(f"Vector query failed: {e}")

    # Fallback: return unfiltered candidates
    return poi_ids
