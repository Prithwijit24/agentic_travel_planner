"""Graph-based retrieval from Neo4j.

Provides functions to get POI candidates by destination,
enrich POI records, and get dynamic interest tags.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from agentic_tour_planner.graphdb.client import GraphDBClient, get_graph_db


def get_graph_db_or_none() -> GraphDBClient | None:
    """Return the graph DB client, or None if unreachable."""
    try:
        client = get_graph_db()
        if client.verify_connectivity():
            return client
        return None
    except Exception as e:
        logger.warning(f"Neo4j unavailable: {e}")
        return None


def get_candidates(destination: str, client: GraphDBClient) -> list[str]:
    """Get all POI IDs under a destination (case-insensitive, partial match)."""
    # Try exact match first, then partial
    queries = [
        """
        MATCH (poi:POI)-[:LOCATED_IN*1..3]->(place:Place)
        WHERE toLower(place.name) = toLower($dest)
        RETURN DISTINCT poi.poi_id AS poi_id
        """,
        """
        MATCH (poi:POI)-[:LOCATED_IN*1..3]->(place:Place)
        WHERE toLower(place.name) CONTAINS toLower($dest)
           OR toLower($dest) CONTAINS toLower(place.name)
        RETURN DISTINCT poi.poi_id AS poi_id
        """,
    ]

    for query in queries:
        results = client.run_query(query, {"dest": destination})
        poi_ids = [r["poi_id"] for r in results if r.get("poi_id")]
        if poi_ids:
            logger.info(f"Found {len(poi_ids)} candidates for '{destination}' via Neo4j")
            return poi_ids

    return []


def enrich(poi_ids: list[str], client: GraphDBClient) -> list[dict[str, Any]]:
    """Return full POI records for given IDs."""
    if not poi_ids:
        return []
    query = """
    MATCH (poi:POI {poi_id: $poi_id})
    RETURN poi {
        .poi_id, .name, .category, .address, .lat, .long,
        .hours, .price, .phone, .long_description, .base_page
    } AS poi
    """
    results = []
    # Batch in groups to avoid huge queries
    batch_size = 100
    for i in range(0, len(poi_ids), batch_size):
        batch = poi_ids[i:i + batch_size]
        batch_results = client.run_query(
            """
            UNWIND $ids AS poi_id
            MATCH (poi:POI {poi_id: poi_id})
            RETURN poi {
                .poi_id, .name, .category, .address, .lat, .long,
                .hours, .price, .phone, .long_description, .base_page
            } AS poi
            """,
            {"ids": batch},
        )
        results.extend([r["poi"] for r in batch_results if r.get("poi")])

    return results


def get_available_tags(destination: str, client: GraphDBClient, limit: int = 10) -> list[str]:
    """Get distinct POI categories for a destination, ordered by frequency."""
    query = """
    MATCH (poi:POI)-[:LOCATED_IN*1..3]->(place:Place)
    WHERE toLower(place.name) = toLower($dest)
       OR toLower(place.name) CONTAINS toLower($dest)
    RETURN DISTINCT poi.category AS tag, count(poi) AS cnt
    ORDER BY cnt DESC
    LIMIT $limit
    """
    results = client.run_query(query, {"dest": destination, "limit": limit})
    return [r["tag"] for r in results if r.get("tag")]


def get_balanced_default_pois(
    destination: str,
    client: GraphDBClient,
    limit_per_category: int = 3,
) -> list[str]:
    """Get a balanced spread of POIs across categories when no interests selected."""
    query = """
    MATCH (poi:POI)-[:LOCATED_IN*1..3]->(place:Place)
    WHERE toLower(place.name) = toLower($dest)
       OR toLower(place.name) CONTAINS toLower($dest)
    WITH poi.category AS category, poi.poi_id AS poi_id
    WITH category, collect(poi_id)[0..$limit_cat] AS pois
    UNWIND pois AS poi_id
    RETURN DISTINCT poi_id
    """
    results = client.run_query(query, {"dest": destination, "limit_cat": limit_per_category})
    return [r["poi_id"] for r in results if r.get("poi_id")]
