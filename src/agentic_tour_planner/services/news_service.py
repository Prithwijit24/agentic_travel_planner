"""Fetch and summarize recent news about a destination using DDGS."""

from __future__ import annotations

from datetime import datetime

from ddgs import DDGS
from pydantic import BaseModel

from agentic_tour_planner.cache.redis_cache import RedisCache
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_CACHE_TTL = 3600  # 1 hour


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
    """Fetch and summarize recent news about a destination using DDGS."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self.llm = llm or LLMProvider()
        self.cache = RedisCache()

    async def collect(
        self,
        destination: str,
        interests: list[str] | None = None,
    ) -> NewsDigest:
        """Fetch news, deduplicate, LLM-summarize, cache."""
        cache_key = f"news:{destination}"

        # Check cache
        try:
            cached = await self.cache.get_json(cache_key)
            if cached:
                logger.info(f"[news] cache hit for {destination}")
                return NewsDigest(**cached)
        except Exception as exc:
            logger.debug(f"[news] cache read failed: {exc}")

        # Fetch from DDGS
        topics = ", ".join(interests) if interests else ""
        query = f"{destination} {topics}".strip()
        try:
            raw = list(DDGS().news(query, max_results=10, timelimit="m"))
        except Exception as exc:
            logger.warning(f"[news] DDGS news failed for {destination}: {exc}")
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
                    date=item.get("date"),
                    snippet=item.get("body", ""),
                )
            )

        if not articles:
            return NewsDigest(
                destination=destination,
                overview="No recent news found for this destination.",
                fetched_at=datetime.now(datetime.UTC).isoformat(),
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
            fetched_at=datetime.now(datetime.UTC).isoformat(),
        )

        # Cache for 1 hour
        try:
            await self.cache.set_json(cache_key, digest.model_dump(), ttl=_CACHE_TTL)
        except Exception as exc:
            logger.debug(f"[news] cache write failed: {exc}")

        return digest

    async def _summarize_overview(self, destination: str, articles: list[NewsArticle]) -> str:
        """LLM generates a 3-5 sentence overview."""
        headlines = "\n".join(f"- {a.title} ({a.source})" for a in articles[:10])
        prompt = (
            f"Recent news about {destination}:\n{headlines}\n\n"
            f"Write a 3-5 sentence overview of what's currently happening in {destination}. "
            f"Be factual and concise. Return only the summary text, no JSON."
        )
        result = await self.llm.complete_json(prompt, role="worker")
        return str(result) if result else f"Recent news about {destination}."

    async def _summarize_article(self, article: NewsArticle) -> str:
        """LLM generates a 1-2 sentence summary."""
        prompt = (
            f"Title: {article.title}\n"
            f"Source: {article.source}\n"
            f"Snippet: {article.snippet}\n\n"
            f"Write a 1-2 sentence factual summary of this news article. Return only the summary text, no JSON."
        )
        result = await self.llm.complete_json(prompt, role="worker")
        return str(result) if result else article.snippet[:200]
