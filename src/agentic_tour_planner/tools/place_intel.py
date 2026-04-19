from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlaceHours
from agentic_tour_planner.tools.web_search import WebSearchTool


class PlaceIntelTool:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.search_tool = WebSearchTool()

    async def lookup_opening_hours(self, venue: str, destination: str) -> PlaceHours:
        if self.settings.google_maps_api_key:
            google_result = await self._lookup_with_google_places(venue, destination)
            if google_result:
                return google_result
        return await self._lookup_with_search(venue, destination)

    async def _lookup_with_google_places(self, venue: str, destination: str) -> PlaceHours | None:
        query = quote_plus(f"{venue}, {destination}")
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={"query": query, "key": self.settings.google_maps_api_key},
            )
            response.raise_for_status()
        payload = response.json()
        if not payload.get("results"):
            return None
        place = payload["results"][0]
        return PlaceHours(
            venue=venue,
            opening_hours=place.get("opening_hours", {}).get("weekday_text", []),
            status=place.get("business_status"),
            source=place.get("place_id"),
            url=place.get("website"),
        )

    async def _lookup_with_search(self, venue: str, destination: str) -> PlaceHours:
        results = self.search_tool.search_opening_hours(venue, destination)
        first = results[0] if results else None
        return PlaceHours(
            venue=venue,
            opening_hours=[first.snippet] if first and first.snippet else [],
            status="search_inferred" if first else "unavailable",
            source=first.url if first else None,
            url=first.url if first else None,
        )

