from __future__ import annotations

import hashlib

from ddgs import DDGS

from agentic_tour_planner.cache import RedisCache
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SearchResult
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class WebSearchTool:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache = RedisCache()

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        logger.debug(f"search called query={query!r} max_results={max_results}")
        cache_key = self._cache_key(query, max_results)
        cached = await self.cache.get_json(cache_key)
        if cached:
            cached_results = [SearchResult(**item) for item in cached.get("results", [])]
            logger.debug(f"search cache hit for {query!r}: {len(cached_results)} result(s)")
            return cached_results

        # Cascade: Tavily (primary) -> SerpAPI -> DuckDuckGo (fallback only).
        for backend, fetcher in (
            ("tavily", self._search_tavily),
            ("serpapi", self._search_serpapi),
            ("ddgs", self._search_ddgs),
        ):
            try:
                logger.info(f"Searching {backend} for {query!r} (max_results={max_results})")
                results = await fetcher(query, max_results)
                if results:
                    logger.info(f"{backend} returned {len(results)} hit(s) for {query!r}")
                    if self.cache.enabled:
                        await self.cache.set_json(
                            cache_key,
                            {"results": [r.model_dump() for r in results]},
                        )
                    return results
                logger.debug(f"{backend} returned no hits for {query!r}")
            except Exception as exc:
                logger.warning(f"[web-search] {backend} failed: {exc}")
        logger.warning(f"All search backends exhausted for {query!r}; returning empty")
        return []

    async def _search_tavily(self, query: str, max_results: int) -> list[SearchResult]:
        key = getattr(self.settings, "tavily_api_key", None)
        if not key:
            logger.debug("[web-search] tavily api_key not set, skipping")
            return []
        try:
            from tavily import TavilyClient
        except Exception as exc:
            logger.warning(f"[web-search] tavily package missing: {exc}")
            return []
        client = TavilyClient(api_key=key)
        data = client.search(query=query, max_results=max_results, include_raw_content=False)
        results = data.get("results", []) or []
        return [
            SearchResult(
                title=r.get("title", ""),
                url=str(r.get("url", "")),
                snippet=r.get("content", "") or r.get("snippet", ""),
            )
            for r in results[:max_results]
            if r.get("url")
        ]

    async def _search_serpapi(self, query: str, max_results: int) -> list[SearchResult]:
        key = getattr(self.settings, "serpapi_api_key", None) or getattr(self.settings, "serp_api_key", None)
        if not key:
            logger.debug("[web-search] serpapi api_key not set, skipping")
            return []
        try:
            from serpapi import GoogleSearch
        except Exception as exc:
            logger.warning(f"[web-search] serpapi package missing: {exc}")
            return []
        raw = GoogleSearch({"engine": "google", "q": query, "num": max_results, "api_key": key}).get_dict()
        items = raw.get("organic_results", []) or []
        return [
            SearchResult(
                title=it.get("title", ""),
                url=str(it.get("link", "")),
                snippet=it.get("snippet", ""),
            )
            for it in items[:max_results]
            if it.get("link")
        ]

    async def _search_ddgs(self, query: str, max_results: int) -> list[SearchResult]:
        logger.info(f"Falling back to DuckDuckGo for {query!r} (max_results={max_results})")
        results = list(DDGS().text(query, max_results=max_results))
        return [
            SearchResult(
                title=item.get("title") or item.get("heading") or query,
                url=item.get("href") or item.get("url") or "",
                snippet=item.get("body") or item.get("snippet") or "",
            )
            for item in results
        ]

    async def search_opening_hours(self, venue: str, destination: str) -> list[SearchResult]:
        logger.debug(f"search_opening_hours called venue={venue!r} destination={destination!r}")
        return await self.search(f"{venue} {destination} opening hours official site", max_results=3)

    async def suggest_places(self, destination: str, interests: list[str], max_results: int = 8) -> list[SearchResult]:
        logger.debug(
            f"suggest_places called destination={destination!r} interests={interests} max_results={max_results}"
        )
        topics = ", ".join(interests) if interests else "best places"
        return await self.search(f"{destination} {topics}", max_results=max_results)

    @staticmethod
    def _cache_key(query: str, max_results: int) -> str:
        digest = hashlib.sha256(f"{query}:{max_results}".encode()).hexdigest()
        return f"websearch:{digest}"
