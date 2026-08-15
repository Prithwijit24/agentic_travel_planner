"""AI Infra Stack API fallback retrieval.

Used when Neo4j or ChromaDB are unavailable.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.tools.api_client import ApiClient


def _get_client() -> ApiClient | None:
    try:
        return ApiClient()
    except Exception as e:
        logger.warning(f"AI Infra Stack API client unavailable: {e}")
        return None


def get_candidates(destination: str) -> list[str]:
    """Search for POIs via AI Infra Stack API."""
    client = _get_client()
    if not client:
        return []
    try:
        result = client.browse(f"travel {destination} places to visit")
        if result and isinstance(result, dict):
            # Extract POI-like entities from browse results
            return _extract_poi_ids_from_text(result.get("content", ""))
    except Exception as e:
        logger.warning(f"API candidate search failed: {e}")
    return []


def filter_by_interest(poi_ids: list[str], _interest_tags: list[str], top_k: int | None = None) -> list[str]:
    """Filter via API-based relevance (fallback: return as-is)."""
    if top_k is None:
        top_k = get_settings().retrieval_api_top_k
    # Without vector DB, return top_k by original order
    return poi_ids[:top_k]


def enrich(poi_ids: list[str]) -> list[dict[str, Any]]:
    """Enrich POIs via API (fallback: minimal records)."""
    return [{"poi_id": pid, "name": pid.split("__")[-1].replace("_", " ").title()} for pid in poi_ids]


def get_available_tags(_destination: str, limit: int = 10) -> list[str]:
    """Default tags when graph DB is unavailable."""
    return ["see", "do", "eat", "drink", "sleep", "buy"][:limit]


def get_balanced_default_pois(_destination: str, _limit_per_category: int = 3) -> list[str]:
    """Fallback returns empty — API mode doesn't support balanced selection without graph."""
    return []


def _extract_poi_ids_from_text(text: str) -> list[str]:
    """Extract potential POI names from browse output."""
    if not text:
        return []
    # Simple extraction: look for capitalized phrases
    import re

    max_names = get_settings().retrieval_api_max_poi_names
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
    return [f"api__{n.lower().replace(' ', '_')}" for n in names[:max_names]]
