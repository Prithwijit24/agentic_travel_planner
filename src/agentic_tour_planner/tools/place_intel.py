from __future__ import annotations

from functools import cached_property
from urllib.parse import quote_plus

import httpx

from agentic_tour_planner.config.settings import Settings, get_settings
from agentic_tour_planner.domain.models import PlaceHours
from agentic_tour_planner.tools.web_search import WebSearchTool
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class PlaceIntel:
    def __init__(self) -> None:
        self._search_tool = WebSearchTool()

    @cached_property
    def settings(self) -> Settings:
        return get_settings()

    @property
    def _timeout(self) -> float:
        return getattr(self.settings, "request_timeout_seconds", 20.0)

    async def lookup_opening_hours(self, venue: str, destination: str) -> PlaceHours:
        logger.debug(f"lookup_opening_hours called venue={venue!r} destination={destination!r}")
        maps_key = getattr(self.settings, "google_maps_api_key", None) or getattr(self.settings, "google_places_api_key", None)
        if maps_key:
            logger.debug("google maps/places api_key=<set>, trying Google Places")
            google_result = await self._lookup_with_google_places(venue, destination, api_key=maps_key)
            if google_result:
                return google_result
            logger.debug("Google Places returned nothing, falling back to search")
        return await self._lookup_with_search(venue, destination)

    async def _lookup_with_google_places(self, venue: str, destination: str, api_key: str) -> PlaceHours | None:
        logger.debug(f"_lookup_with_google_places called venue={venue!r} destination={destination!r} api_key=<set>")
        query = quote_plus(f"{venue}, {destination}")
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            logger.info(f"Calling Google Places textsearch API for {venue!r}, {destination!r}")
            from agentic_tour_planner.tools.http_util import aretry_get

            response = await aretry_get(
                client,
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={"query": query, "key": api_key},
            )
            response.raise_for_status()
        payload = response.json()
        if not payload.get("results"):
            logger.debug(f"Google Places returned no results for {venue!r}, {destination!r}")
            return None
        place = payload["results"][0]
        logger.debug(f"Google Places returned {len(payload['results'])} result(s) for {venue!r}")
        return PlaceHours(
            venue=venue,
            opening_hours=place.get("opening_hours", {}).get("weekday_text", []),
            status=place.get("business_status"),
            source=place.get("place_id"),
            url=place.get("website"),
        )

    async def _lookup_with_search(self, venue: str, destination: str) -> PlaceHours:
        logger.debug(f"_lookup_with_search called venue={venue!r} destination={destination!r}")
        results = await self._search_tool.search_opening_hours(venue, destination)
        first = results[0] if results else None
        logger.debug(f"_lookup_with_search for {venue!r}: {'inferred from search' if first else 'unavailable'}")
        return PlaceHours(
            venue=venue,
            opening_hours=[first.snippet] if first and first.snippet else [],
            status="search_inferred" if first else "unavailable",
            source=first.url if first else None,
            url=first.url if first else None,
        )


async def lookup_opening_hours(venue: str, destination: str) -> PlaceHours:
    return await PlaceIntel().lookup_opening_hours(venue, destination)
