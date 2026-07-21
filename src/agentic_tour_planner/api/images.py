from __future__ import annotations

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlaceImage
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


async def _fetch_unsplash(query: str) -> str | None:
    settings = get_settings()
    if not settings.unsplash_access_key:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1},
                headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            if results:
                return results[0]["urls"]["regular"]
    except Exception as exc:
        logger.warning(f"Unsplash search failed for {query!r}: {exc}")
    return None


async def _fetch_pexels(query: str) -> str | None:
    settings = get_settings()
    if not settings.pexels_api_key:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1},
                headers={"Authorization": settings.pexels_api_key},
                timeout=10,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                return photos[0]["src"]["large"]
    except Exception as exc:
        logger.warning(f"Pexels search failed for {query!r}: {exc}")
    return None


async def resolve_images(places: list[dict]) -> list[PlaceImage]:
    settings = get_settings()
    results = []
    for place in places:
        query = place.get("image_query", "")
        name = place.get("place_name", "")

        if settings.image_provider == "pexels":
            url = await _fetch_pexels(query)
            source = "pexels"
        else:
            url = await _fetch_unsplash(query)
            source = "unsplash"

        results.append(PlaceImage(
            place_name=name,
            image_query=query,
            image_url=url,
            source=source if url else None,
        ))
    return results
