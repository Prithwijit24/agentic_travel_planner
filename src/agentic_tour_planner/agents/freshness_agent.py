"""Freshness agent - checks and refreshes stale POIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from agentic_tour_planner.graphdb.client import get_graph_db
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.vectordb.client import get_vector_db

FRESHNESS_THRESHOLD_DAYS = 180  # 6 months

REFRESH_SYSTEM_PROMPT = (
    "You are a travel content writer. Given a place name and destination, "
    "write a concise 2-3 sentence description of the place for a travel itinerary.\n"
    "Return strict JSON only with keys: long_description, short_highlight"
)


async def check_and_refresh(poi: dict[str, Any], destination: str) -> dict[str, Any]:
    """Check if a POI is stale and refresh if needed."""
    if not _is_stale(poi):
        return poi

    logger.info("Refreshing stale POI: " + str(poi.get("name", poi.get("poi_id", "?"))))

    try:
        description = await _fetch_fresh_description(poi, destination)
        if description:
            poi["long_description"] = description.get("long_description", poi.get("long_description", ""))
            poi["short_highlight"] = description.get("short_highlight", "")
            poi["last_verified"] = datetime.now(timezone.utc).isoformat()
            _persist_refresh(poi)
    except Exception as e:
        logger.warning("Freshness refresh failed for " + str(poi.get("name", "?")) + ": " + str(e))

    return poi


async def refresh_pois(pois: list[dict[str, Any]], destination: str) -> list[dict[str, Any]]:
    """Refresh all stale POIs in a list. Only stale POIs trigger LLM calls."""
    refreshed = []
    stale_count = 0
    for poi in pois:
        if _is_stale(poi):
            stale_count += 1
        refreshed.append(await check_and_refresh(poi, destination))

    if stale_count:
        logger.info("Freshness: " + str(stale_count) + "/" + str(len(pois)) + " POIs were stale and refreshed")
    else:
        logger.info("Freshness: all " + str(len(pois)) + " POIs are fresh")

    return refreshed


def _is_stale(poi: dict[str, Any]) -> bool:
    """Check if a POI needs refreshing."""
    desc = poi.get("long_description", "").strip()
    if not desc or len(desc) < 20:
        return True

    last_verified = poi.get("last_verified")
    if last_verified:
        try:
            verified_date = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - verified_date
            if age > timedelta(days=FRESHNESS_THRESHOLD_DAYS):
                return True
        except (ValueError, TypeError):
            pass

    return False


async def _fetch_fresh_description(poi: dict[str, Any], destination: str) -> dict[str, Any] | None:
    """Fetch fresh description for a POI using one LLM call."""
    provider = LLMProvider()
    prompt = "Place: " + str(poi.get("name", "?")) + "\nDestination: " + str(destination)
    if poi.get("category"):
        prompt += "\nCategory: " + str(poi["category"])

    result = await provider.complete_json(prompt, system_prompt=REFRESH_SYSTEM_PROMPT)
    return result if result.get("long_description") else None


def _persist_refresh(poi: dict[str, Any]) -> None:
    """Write refreshed data to both Neo4j and ChromaDB."""
    try:
        client = get_graph_db()
        client.run_query(
            "MATCH (p:POI {poi_id: $poi_id}) SET p.long_description = $desc, p.last_verified = $verified",
            {"poi_id": poi.get("poi_id"), "desc": poi.get("long_description", ""), "verified": poi.get("last_verified", "")},
        )
    except Exception as e:
        logger.warning("Neo4j persist failed for " + str(poi.get("poi_id", "?")) + ": " + str(e))

    try:
        vclient = get_vector_db()
        vclient.upsert(
            ids=[poi["poi_id"]],
            documents=[poi.get("long_description", "")],
            metadatas=[{"poi_id": poi.get("poi_id"), "name": poi.get("name", ""), "category": poi.get("category", ""), "region": poi.get("base_page", "")}],
        )
    except Exception as e:
        logger.warning("ChromaDB persist failed for " + str(poi.get("poi_id", "?")) + ": " + str(e))
