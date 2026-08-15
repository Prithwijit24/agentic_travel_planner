"""Fetch and summarize recent news about a destination.

Uses the AI Infra Stack /news endpoint when available, with DDGS fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_MEMORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class NewsArticle(BaseModel):
    title: str
    url: str
    source: str
    date: str | None = None
    snippet: str
    summary: str = ""


class NewsDigest(BaseModel):
    destination: str
    overview: str = ""
    articles: list[NewsArticle] = []
    fetched_at: str = ""


class NewsService:
    """Fetch and summarize recent news about a destination.

    Uses the AI Infra Stack /news endpoint when available, with DDGS fallback.
    """

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self.llm = llm or LLMProvider()

    async def _fetch_from_stack(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """Try fetching news from AI Infra Stack /news endpoint."""
        from agentic_tour_planner.tools.ai_stack_client import AiStackClient

        stack = AiStackClient()
        try:
            result = await stack.news(query=query, max_results=max_results, timelimit="m")
            # API returns {"results": [...]} not {"articles": [...]}
            return cast(list[dict[Any, Any]], result.get("results", []))
        except Exception as exc:
            logger.debug(f"[news] AI Stack /news failed, falling back to DDGS: {exc}")
            return []
        finally:
            stack.close()

    async def _fetch_from_ddgs(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """Fallback: fetch news from DDGS directly."""
        from ddgs import DDGS

        try:
            items = list(DDGS().news(query, max_results=max_results, timelimit="m"))
            return [dict(item) for item in items]
        except Exception as exc:
            logger.warning(f"[news] DDGS news failed for {query!r}: {exc}")
            return []

    async def collect(
        self,
        destination: str,
        interests: list[str] | None = None,
    ) -> NewsDigest:
        """Fetch news, deduplicate, LLM-summarize, cache (in-memory, 1h TTL)."""
        cache_key = f"news:{destination}"
        now = datetime.now(UTC).timestamp()

        cached = _MEMORY_CACHE.get(cache_key)
        ttl = get_settings().news_cache_ttl_seconds
        if cached and now - cached[0] < ttl:
            logger.info(f"[news] cache hit for {destination}")
            return NewsDigest(**cached[1])

        # Fetch news: AI Stack first, DDGS fallback
        topics = ", ".join(interests) if interests else ""
        query = f"{destination} {topics}".strip()
        raw = await self._fetch_from_stack(query)
        if not raw:
            raw = await self._fetch_from_ddgs(query)
        if not raw:
            return NewsDigest(destination=destination, overview="Unable to fetch news.")

        # Deduplicate by URL
        articles: list[NewsArticle] = []
        seen_urls: set[str] = set()
        for item in raw:
            url = item.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            articles.append(
                NewsArticle(
                    title=item.get("title", ""),
                    url=url,
                    source=item.get("source", ""),
                    date=item.get("published") or item.get("date"),
                    snippet=item.get("body", "") or item.get("snippet", ""),
                )
            )

        if not articles:
            return NewsDigest(
                destination=destination,
                overview="No recent news found for this destination.",
                fetched_at=datetime.now(UTC).isoformat(),
            )

        # LLM summarization
        overview = f"Recent news about {destination}."
        try:
            overview = await self._summarize_overview(destination, articles)
            for article in articles[:5]:
                article.summary = await self._summarize_article(article)
        except Exception as exc:
            logger.warning(f"[news] LLM summarization failed: {exc}")
            # Fall back to raw snippets
            for article in articles:
                article.summary = article.snippet[:200]

        digest = NewsDigest(
            destination=destination,
            overview=overview,
            articles=articles[:5],
            fetched_at=datetime.now(UTC).isoformat(),
        )

        _MEMORY_CACHE[cache_key] = (now, digest.model_dump())

        return digest

    async def _summarize_overview(self, destination: str, articles: list[NewsArticle]) -> str:
        """LLM generates a 3-5 sentence overview."""
        headlines = "\n".join(f"- {a.title} ({a.source})" for a in articles[:10])
        prompt = (
            f"Recent news about {destination}:\n{headlines}\n\n"
            f"Write a 3-5 sentence overview of what's currently happening in {destination}. "
            f"Be factual and concise. Return only the summary text, no JSON."
        )
        result = await self.llm.complete_text(prompt, role="worker")
        return str(result) if result else f"Recent news about {destination}."

    async def _summarize_article(self, article: NewsArticle) -> str:
        """LLM generates a 1-2 sentence summary."""
        prompt = (
            f"Title: {article.title}\n"
            f"Source: {article.source}\n"
            f"Snippet: {article.snippet}\n\n"
            f"Write a 1-2 sentence factual summary of this news article. Return only the summary text, no JSON."
        )
        result = await self.llm.complete_text(prompt, role="worker")
        return str(result) if result else article.snippet[:200]
