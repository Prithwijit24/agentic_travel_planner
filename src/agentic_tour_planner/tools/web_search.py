from __future__ import annotations

from duckduckgo_search import DDGS

from agentic_tour_planner.domain.models import SearchResult


class WebSearchTool:
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        results = DDGS().text(query, max_results=max_results)
        return [
            SearchResult(
                title=item.get("title") or item.get("heading") or query,
                url=item.get("href") or item.get("url") or "",
                snippet=item.get("body") or item.get("snippet") or "",
            )
            for item in results
        ]

    def search_opening_hours(self, venue: str, destination: str) -> list[SearchResult]:
        return self.search(f"{venue} {destination} opening hours official site", max_results=3)

    def suggest_places(self, destination: str, interests: list[str], max_results: int = 8) -> list[SearchResult]:
        topics = ", ".join(interests) if interests else "best places"
        return self.search(f"{destination} {topics}", max_results=max_results)

