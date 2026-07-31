from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.tools.web_search import WebSearchTool
from agentic_tour_planner.utils.logging import get_logger

_YOUTUBE_CUTOFF_DAYS = 730  # "last 2 years"
_MIN_VIDEO_MINUTES = 20

logger = get_logger(__name__)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    kind: str  # "video" | "web"
    duration_seconds: int | None = None
    published_date: str | None = None
    source: str = "unknown"  # which backend produced it (serpapi/tavily/ddgs)


def parse_duration(value: Any) -> int | None:
    """Parse a duration into seconds. Handles '20:15', 'PT20M15S', '20 min', '1h2m'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text, re.IGNORECASE)
    if m:
        h, mi, s = (int(x) if x else 0 for x in m.groups())
        if h or mi or s:
            return h * 3600 + mi * 60 + s
    parts = text.split(":")
    if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
        parts = [int(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    total = 0
    for num, unit in re.findall(r"(\d+)\s*(h|hr|hour|hrs|m|min|minute|mins|s|sec)", text, re.IGNORECASE):
        unit = unit.lower()
        if unit.startswith("h"):
            total += int(num) * 3600
        elif unit.startswith("m"):
            total += int(num) * 60
        else:
            total += int(num)
    return total or None


def parse_published(value: Any) -> str | None:
    """Best-effort normalisation of a published-date string to ISO date."""
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except Exception:
        pass
    m = re.match(r"(\d+)\s*(year|month|week|day|hour)s?\s*ago", text, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        delta = {
            "year": timedelta(days=365 * n),
            "month": timedelta(days=30 * n),
            "week": timedelta(weeks=n),
            "day": timedelta(days=n),
            "hour": timedelta(hours=n),
        }.get(unit)
        if delta:
            return (datetime.now() - delta).date().isoformat()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except Exception:
            continue
    return None


class SearchProvider:
    """Internet search with a cascading backend: DuckDuckGo -> Tavily -> SerpAPI.

    DuckDuckGo is the primary (free, no API key needed); on failure/empty we fall
    through to Tavily, then to SerpAPI as a last resort. Each backend returns
    :class:`SearchHit` objects so the caller can filter videos by duration /
    recency.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._ddgs = WebSearchTool()

    async def search(self, query: str, kind: str = "web", max_results: int = 5) -> list[SearchHit]:
        kind = "video" if kind == "video" else "web"
        logger.debug(f"search called query={query!r} kind={kind} max_results={max_results}")
        # Tavily is web-only; for video searches it returns web pages with no real
        # video metadata (duration/published). SerpAPI's YouTube engine and DDGS video
        # search return proper results, so skip Tavily for video queries.
        backends = ("serpapi", self._search_serpapi) if kind == "video" else ("tavily", self._search_tavily)
        if kind == "video":
            backends = (
                ("ddgs", self._search_ddgs),
                ("serpapi", self._search_serpapi),
            )
        else:
            backends = (
                ("ddgs", self._search_ddgs),
                ("tavily", self._search_tavily),
                ("serpapi", self._search_serpapi),
            )
        for backend, fetcher in backends:
            try:
                logger.debug(f"[search] trying backend {backend} for {query!r}")
                hits = await fetcher(query, kind, max_results)
                if hits:
                    logger.info(f"[search] {backend} returned {len(hits)} hit(s) for {query!r}")
                    return hits
                logger.debug(f"[search] {backend} returned no hits for {query!r}")
            except Exception as exc:
                logger.warning(f"[search] {backend} failed: {exc}")
        logger.debug(f"[search] all backends exhausted for {query!r}, returning empty")
        return []

    async def _search_serpapi(self, query: str, kind: str, max_results: int) -> list[SearchHit]:
        serpapi_key = getattr(self.settings, "serpapi_api_key", None) or getattr(self.settings, "serp_api_key", None)
        if not serpapi_key:
            logger.debug("[search] serpapi api_key not set, skipping serpapi")
            return []
        logger.debug(f"_search_serpapi called query={query!r} kind={kind} api_key=<set>")
        try:
            from serpapi import GoogleSearch
        except Exception as exc:
            logger.warning(f"[search] serpapi package missing: {exc}")
            return []

        if kind == "video":
            logger.info(f"Calling SerpAPI (youtube) for {query!r}")
            params = {
                "engine": "youtube",
                "search_query": query,
                "api_key": serpapi_key,
            }
            raw = GoogleSearch(params).get_dict()
            items = raw.get("video_results", []) or []
            logger.debug(f"serpapi youtube returned {len(items)} video result(s) for {query!r}")
            hits = []
            for it in items[:max_results]:
                link = it.get("link") or it.get("url")
                if not link:
                    continue
                hits.append(
                    SearchHit(
                        title=it.get("title", ""),
                        url=link,
                        snippet=it.get("snippet") or it.get("description") or "",
                        kind="video",
                        duration_seconds=parse_duration(it.get("duration") or _yt_duration_from_snippet(it)),
                        published_date=parse_published(it.get("date")),
                        source="serpapi",
                    )
                )
            return hits

        logger.info(f"Calling SerpAPI (google) for {query!r}")
        params = {
            "engine": "google",
            "q": query,
            "num": max_results,
            "api_key": serpapi_key,
        }
        raw = GoogleSearch(params).get_dict()
        items = raw.get("organic_results", []) or []
        logger.debug(f"serpapi google returned {len(items)} organic result(s) for {query!r}")
        return [
            SearchHit(
                title=it.get("title", ""),
                url=it.get("link", ""),
                snippet=it.get("snippet", ""),
                kind="web",
                published_date=parse_published(it.get("date")),
                source="serpapi",
            )
            for it in items[:max_results]
            if it.get("link")
        ]

    async def _search_tavily(self, query: str, kind: str, max_results: int) -> list[SearchHit]:
        if not self.settings.tavily_api_key:
            logger.debug("[search] tavily api_key not set, skipping tavily")
            return []
        logger.debug(f"_search_tavily called query={query!r} kind={kind} api_key=<set>")
        try:
            from tavily import TavilyClient
        except Exception as exc:
            logger.warning(f"[search] tavily package missing: {exc}")
            return []

        client = TavilyClient(api_key=self.settings.tavily_api_key)
        logger.info(f"Calling Tavily search for {query!r}")
        data = client.search(query=query, max_results=max_results, include_raw_content=False)
        results = data.get("results", []) or []
        logger.debug(f"tavily returned {len(results)} result(s) for {query!r}")
        # Tavily is web-only; if asked for videos we still return what it finds
        # (duration/recency simply won't be available for filtering).
        return [
            SearchHit(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", "") or r.get("snippet", ""),
                kind=kind,
                published_date=parse_published(r.get("published_date")),
                source="tavily",
            )
            for r in results[:max_results]
            if r.get("url")
        ]

    async def _search_ddgs(self, query: str, kind: str, max_results: int) -> list[SearchHit]:
        logger.debug(f"_search_ddgs called query={query!r} kind={kind} max_results={max_results}")
        if kind == "video":
            try:
                from ddgs import DDGS

                logger.info(f"Calling DDGS videos for {query!r}")
                items = list(DDGS().videos(query, max_results=max_results))
            except Exception as exc:
                logger.warning(f"[search] ddgs videos failed: {exc}")
                return []
            logger.debug(f"ddgs videos returned {len(items)} item(s) for {query!r}")
            hits = []
            for it in items:
                url = it.get("url") or it.get("href") or it.get("content")
                if not url:
                    continue
                hits.append(
                    SearchHit(
                        title=it.get("title", ""),
                        url=url,
                        snippet=it.get("snippet") or it.get("description") or "",
                        kind="video",
                        duration_seconds=parse_duration(it.get("duration")),
                        published_date=parse_published(it.get("publish_time") or it.get("published")),
                        source="ddgs",
                    )
                )
            return hits

        logger.info(f"Calling DDGS web search for {query!r}")
        results = list(await self._ddgs.search(query, max_results=max_results))
        logger.debug(f"ddgs web returned {len(results)} result(s) for {query!r}")
        return [
            SearchHit(
                title=r.title,
                url=str(r.url),
                snippet=r.snippet,
                kind="web",
                source="ddgs",
            )
            for r in results
        ]


def _yt_duration_from_snippet(item: dict) -> str | None:
    """YouTube results sometimes bury duration in the snippet; best-effort grab."""
    snippet = item.get("snippet") or item.get("description") or ""
    m = re.search(r"(\d+:\d{2}(?::\d{2})?)", snippet)
    return m.group(1) if m else None
