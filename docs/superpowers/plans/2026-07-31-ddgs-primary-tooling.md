# DDGS Primary Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DuckDuckGo Search (`ddgs`) the primary tool for search, images, videos, and content extraction, with existing paid/API backends as fallbacks. Add a News feature to the Streamlit UI.

**Architecture:** Flip existing cascade orders so DDGS runs first (no API key needed). Add `fetch_ddgs_images()` to the image waterfall as #1 primary. Add `DDGS().extract()` as first fallback in the web crawler. Create a new `NewsService` module and Streamlit "📰 News" tab.

**Tech Stack:** `ddgs` (DuckDuckGo Search), Pydantic, Streamlit, Redis cache

## Global Constraints

- Python ≥3.11
- All DDGS calls must be wrapped in try/except — failures never crash the pipeline
- No removal of existing backends — all kept as fallbacks
- Existing tests must continue to pass
- Follow existing code patterns (async, RedisCache, get_logger, get_settings)
- DDGS requires no API key — this is the primary motivation

---

## Task 1: Flip Search Cascade — DDGS First

**Files:**
- Modify: `src/agentic_tour_planner/tools/web_search.py:28-33`
- Modify: `src/agentic_tour_planner/tools/search_provider.py:105-123`
- Test: `tests/unit/test_live_web.py`

**Interfaces:**
- Consumes: `WebSearchTool.search()`, `SearchProvider.search()`
- Produces: Same return types (`list[SearchResult]`, `list[SearchHit]`) — no interface change

- [ ] **Step 1: Flip cascade in `web_search.py`**

In `src/agentic_tour_planner/tools/web_search.py`, change the cascade tuple order in `search()`:

```python
# Lines 28-33 — change from:
        # Cascade: Tavily (primary) -> SerpAPI -> DuckDuckGo (fallback only).
        for backend, fetcher in (
            ("tavily", self._search_tavily),
            ("serpapi", self._search_serpapi),
            ("ddgs", self._search_ddgs),
        ):

# To:
        # Cascade: DuckDuckGo (primary, no API key) -> Tavily -> SerpAPI.
        for backend, fetcher in (
            ("ddgs", self._search_ddgs),
            ("tavily", self._search_tavily),
            ("serpapi", self._search_serpapi),
        ):
```

- [ ] **Step 2: Flip cascade in `search_provider.py`**

In `src/agentic_tour_planner/tools/search_provider.py`, change the `search()` method (lines ~105-123):

```python
# Change the docstring (line ~92):
# Before:
#     """Internet search with a cascading backend: Tavily -> SerpAPI -> DuckDuckGo.
# To:
    """Internet search with a cascading backend: DuckDuckGo -> Tavily -> SerpAPI.

# Change the backends for kind="web" (lines ~112-118):
# Before:
        if kind == "video":
            backends = (
                ("serpapi", self._search_serpapi),
                ("ddgs", self._search_ddgs),
            )
        else:
            backends = (
                ("tavily", self._search_tavily),
                ("serpapi", self._search_serpapi),
                ("ddgs", self._search_ddgs),
            )
# To:
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
```

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `python -m pytest tests/unit/test_live_web.py -v`
Expected: All existing tests pass (cascade order tests may need updating — see Step 4)

- [ ] **Step 4: Update test expectations for new cascade order**

In `tests/unit/test_live_web.py`, the test `test_search_cascade_serpapi_to_ddgs` mocks DDGS as a fallback. After the flip, DDGS is now tried first. Update the test to reflect the new order:

```python
# The test currently mocks tavily to fail, serpapi to fail, then expects ddgs.
# After the flip, ddgs runs FIRST. If DDGS is mocked to succeed, it returns immediately.
# Update the test to mock DDGS first and verify it's called first.
```

Read the test file to understand the exact mock setup, then update accordingly.

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/unit/test_live_web.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/tools/web_search.py src/agentic_tour_planner/tools/search_provider.py tests/unit/test_live_web.py
git commit -m "feat(search): flip cascade to DDGS primary with Tavily/SerpAPI fallback"
```

---

## Task 2: DDGS Images as #1 Primary

**Files:**
- Modify: `src/agentic_tour_planner/images/sources.py` (add `fetch_ddgs_images`)
- Modify: `src/agentic_tour_planner/images/pipeline.py` (add to `_WATERFALL`)
- Test: `tests/unit/test_image_sources.py` (or create if needed)

**Interfaces:**
- Consumes: `ImageCandidate` model from `images/models.py`
- Produces: `fetch_ddgs_images(place_name: str) -> list[ImageCandidate]`

- [ ] **Step 1: Write the failing test**

Create or update `tests/unit/test_image_sources.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.anyio
async def test_fetch_ddgs_images_returns_candidates():
    """DDGS images should return ImageCandidate objects."""
    from agentic_tour_planner.images.sources import fetch_ddgs_images

    mock_items = [
        {"image": "https://example.com/img1.jpg", "thumbnail": "https://example.com/thumb1.jpg", "width": 800, "height": 600, "source": "example.com"},
        {"image": "https://example.com/img2.jpg", "thumbnail": "https://example.com/thumb2.jpg", "width": 1024, "height": 768, "source": "example.com"},
    ]

    with patch("agentic_tour_planner.images.sources.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.images.return_value = iter(mock_items)
        mock_ddgs.return_value = mock_instance

        results = await fetch_ddgs_images("Kyoto")

    assert len(results) == 2
    assert results[0].url == "https://example.com/img1.jpg"
    assert results[0].source == "ddgs"
    assert results[0].verified is False
    assert results[0].license is None


@pytest.mark.anyio
async def test_fetch_ddgs_images_handles_empty():
    """DDGS images should return empty list when no results."""
    from agentic_tour_planner.images.sources import fetch_ddgs_images

    with patch("agentic_tour_planner.images.sources.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.images.return_value = iter([])
        mock_ddgs.return_value = mock_instance

        results = await fetch_ddgs_images("NonexistentPlaceXYZ")

    assert results == []


@pytest.mark.anyio
async def test_fetch_ddgs_images_handles_exception():
    """DDGS images should return empty list on error."""
    from agentic_tour_planner.images.sources import fetch_ddgs_images

    with patch("agentic_tour_planner.images.sources.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.images.side_effect = RuntimeError("rate limited")
        mock_ddgs.return_value = mock_instance

        results = await fetch_ddgs_images("Kyoto")

    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_image_sources.py::test_fetch_ddgs_images_returns_candidates -v`
Expected: FAIL with `ImportError` or `AttributeError` (function doesn't exist yet)

- [ ] **Step 3: Implement `fetch_ddgs_images` in `sources.py`**

Add to `src/agentic_tour_planner/images/sources.py`, before the `# ── Internal helpers` section:

```python
# ── 5.0 DuckDuckGo Images (Primary — no API key needed) ─────────────


async def fetch_ddgs_images(place_name: str) -> list[ImageCandidate]:
    """Search DuckDuckGo for images of a place. No API key required."""
    try:
        from ddgs import DDGS

        items = list(DDGS().images(place_name, max_results=5))
        return [
            _make_candidate(
                url=item.get("image") or item.get("thumbnail") or "",
                source="ddgs",
                width=item.get("width"),
                height=item.get("height"),
                license_name=None,  # DDGS doesn't provide license info
                attribution=item.get("source"),
                verified=False,  # Not a curated/open-licensed source
            )
            for item in items
            if item.get("image")
        ]
    except Exception as exc:
        logger.warning(f"fetch_ddgs_images failed for {place_name!r}: {exc}")
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_image_sources.py -v`
Expected: PASS

- [ ] **Step 5: Add to waterfall in `pipeline.py`**

In `src/agentic_tour_planner/images/pipeline.py`, update the import and waterfall:

```python
# Add to imports (line ~17):
from agentic_tour_planner.images.sources import (
    fetch_ddgs_images,     # NEW
    fetch_openverse,
    fetch_stock,
    fetch_mapillary,
    fetch_wikidata,
    fetch_wikimedia_commons,
    fetch_wikipedia,
)

# Update _WATERFALL (line ~24):
_WATERFALL = [
    (fetch_ddgs_images, False),    # NEW — #1 primary, no API key
    (fetch_wikidata, False),
    (fetch_wikimedia_commons, False),
    (fetch_wikipedia, False),
    (fetch_openverse, False),
    (fetch_mapillary, True),
    (fetch_stock, False),
]
```

- [ ] **Step 6: Run image pipeline tests**

Run: `python -m pytest tests/unit/test_image_pipeline.py tests/unit/test_image_sources.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/agentic_tour_planner/images/sources.py src/agentic_tour_planner/images/pipeline.py tests/unit/test_image_sources.py
git commit -m "feat(images): add DDGS as #1 primary image source in waterfall"
```

---

## Task 3: DDGS Extract as First Fallback in Crawler

**Files:**
- Modify: `src/agentic_tour_planner/ingestion/crawler.py`
- Test: `tests/unit/test_crawler.py` (or create if needed)

**Interfaces:**
- Consumes: `CrawlResult` dataclass from `crawler.py`
- Produces: `_fetch_ddgs_extract(url: str) -> CrawlResult | None`

- [ ] **Step 1: Write the failing test**

Create or update `tests/unit/test_crawler.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.anyio
async def test_ddgs_extract_returns_crawl_result():
    """DDGS extract should return a CrawlResult on success."""
    from agentic_tour_planner.ingestion.crawler import WebCrawler

    mock_items = [
        {"title": "Test Page", "content": "This is the extracted content from the page."},
    ]

    crawler = WebCrawler()

    with patch("agentic_tour_planner.ingestion.crawler.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.extract.return_value = iter(mock_items)
        mock_ddgs.return_value = mock_instance

        result = await crawler._fetch_ddgs_extract("https://example.com/article")

    assert result is not None
    assert result.url == "https://example.com/article"
    assert result.title == "Test Page"
    assert "extracted content" in result.content
    assert result.metadata["backend"] == "ddgs_extract"


@pytest.mark.anyio
async def test_ddgs_extract_returns_none_on_empty():
    """DDGS extract should return None when no content."""
    from agentic_tour_planner.ingestion.crawler import WebCrawler

    crawler = WebCrawler()

    with patch("agentic_tour_planner.ingestion.crawler.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.extract.return_value = iter([])
        mock_ddgs.return_value = mock_instance

        result = await crawler._fetch_ddgs_extract("https://example.com/empty")

    assert result is None


@pytest.mark.anyio
async def test_ddgs_extract_returns_none_on_exception():
    """DDGS extract should return None on error (graceful fallback)."""
    from agentic_tour_planner.ingestion.crawler import WebCrawler

    crawler = WebCrawler()

    with patch("agentic_tour_planner.ingestion.crawler.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.extract.side_effect = RuntimeError("blocked")
        mock_ddgs.return_value = mock_instance

        result = await crawler._fetch_ddgs_extract("https://example.com/blocked")

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_crawler.py::test_ddgs_extract_returns_crawl_result -v`
Expected: FAIL (method doesn't exist)

- [ ] **Step 3: Implement `_fetch_ddgs_extract` in `crawler.py`**

Add to `src/agentic_tour_planner/ingestion/crawler.py`, after the `_fetch_scrapling` method:

```python
    async def _fetch_ddgs_extract(self, url: str) -> CrawlResult | None:
        """Fast content extraction via DDGS().extract(). No API key needed."""
        try:
            from ddgs import DDGS

            items = list(DDGS().extract(url))
            if not items:
                return None
            # DDGS extract returns list of dicts with 'title' and 'content'
            content = "\n\n".join(
                item.get("content", "") for item in items if item.get("content")
            )
            title = items[0].get("title", "") if items else ""
            if not content.strip():
                return None
            return CrawlResult(
                url=url,
                title=title or url,
                content=content[:12000],  # bound tokens
                metadata={"backend": "ddgs_extract"},
            )
        except Exception as exc:
            logger.debug(f"DDGS extract failed for {url}: {exc}")
            return None
```

- [ ] **Step 4: Wire into `fetch()` method**

In `src/agentic_tour_planner/ingestion/crawler.py`, modify the `fetch()` method to try DDGS extract first:

```python
    async def fetch(self, url: str, backend: str | None = None) -> CrawlResult:
        # Try DDGS extract first (fast, no API key)
        ddgs_result = await self._fetch_ddgs_extract(url)
        if ddgs_result and ddgs_result.content.strip():
            logger.info(f"DDGS extract succeeded for {url}")
            return ddgs_result

        # Fall back to existing cascade
        resolved_backend = backend or self.settings.web_crawl_backend
        logger.info(f"Fetching url={url} backend={resolved_backend}")
        # ... rest of existing code unchanged
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/unit/test_crawler.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/ingestion/crawler.py tests/unit/test_crawler.py
git commit -m "feat(crawl): add DDGS extract as first fallback in WebCrawler"
```

---

## Task 4: News Service

**Files:**
- Create: `src/agentic_tour_planner/services/news_service.py`
- Test: `tests/unit/test_news_service.py`

**Interfaces:**
- Consumes: `LLMProvider`, `RedisCache`, `DDGS().news()`
- Produces: `NewsService.collect(destination, interests) -> NewsDigest`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_service.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone


@pytest.mark.anyio
async def test_news_service_collect_returns_digest():
    """NewsService.collect should return a NewsDigest with articles."""
    from agentic_tour_planner.services.news_service import NewsService, NewsDigest

    mock_news = [
        {"title": "Kyoto Festival Announced", "url": "https://news.example/1", "source": "Kyoto Times", "date": "2026-07-30", "body": "A new festival is coming to Kyoto."},
        {"title": "New Train Line Opens", "url": "https://news.example/2", "source": "Japan News", "date": "2026-07-29", "body": "A new train line connects Kyoto to Osaka."},
    ]

    service = NewsService(llm=MagicMock())

    # Mock cache miss
    service.cache = MagicMock()
    service.cache.get_json = AsyncMock(return_value=None)
    service.cache.set_json = AsyncMock()

    # Mock DDGS
    with patch("agentic_tour_planner.services.news_service.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.news.return_value = iter(mock_news)
        mock_ddgs.return_value = mock_instance

        # Mock LLM
        service.llm.complete_json = AsyncMock(side_effect=[
            "Kyoto is experiencing exciting developments with new festivals and transport improvements.",
            "Kyoto Times reports on an upcoming cultural festival.",
            "Japan News covers the opening of a new train connection.",
        ])

        digest = await service.collect("Kyoto", interests=["festivals"])

    assert isinstance(digest, NewsDigest)
    assert digest.destination == "Kyoto"
    assert len(digest.articles) == 2
    assert digest.articles[0].title == "Kyoto Festival Announced"
    assert digest.articles[0].summary != ""
    assert "festival" in digest.overview.lower() or "kyoto" in digest.overview.lower()


@pytest.mark.anyio
async def test_news_service_returns_empty_when_no_news():
    """NewsService.collect should return empty digest when no news found."""
    from agentic_tour_planner.services.news_service import NewsService, NewsDigest

    service = NewsService(llm=MagicMock())
    service.cache = MagicMock()
    service.cache.get_json = AsyncMock(return_value=None)

    with patch("agentic_tour_planner.services.news_service.DDGS") as mock_ddgs:
        mock_instance = MagicMock()
        mock_instance.news.return_value = iter([])
        mock_ddgs.return_value = mock_instance

        digest = await service.collect("NonexistentPlaceXYZ")

    assert isinstance(digest, NewsDigest)
    assert digest.articles == []
    assert "no recent news" in digest.overview.lower()


@pytest.mark.anyio
async def test_news_service_uses_cache():
    """NewsService.collect should return cached result when available."""
    from agentic_tour_planner.services.news_service import NewsService, NewsDigest

    cached_digest = {
        "destination": "Kyoto",
        "overview": "Cached overview",
        "articles": [{"title": "Cached", "url": "https://cached", "source": "cache", "date": None, "snippet": "cached", "summary": "cached summary"}],
        "fetched_at": "2026-07-31T00:00:00+00:00",
    }

    service = NewsService(llm=MagicMock())
    service.cache = MagicMock()
    service.cache.get_json = AsyncMock(return_value=cached_digest)

    digest = await service.collect("Kyoto")

    assert digest.overview == "Cached overview"
    assert len(digest.articles) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_news_service.py::test_news_service_collect_returns_digest -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `NewsService`**

Create `src/agentic_tour_planner/services/news_service.py`:

```python
"""Fetch and summarize recent news about a destination using DDGS."""
from __future__ import annotations

from datetime import datetime, timezone

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
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )

        # LLM summarization
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
            fetched_at=datetime.now(timezone.utc).isoformat(),
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/unit/test_news_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/services/news_service.py tests/unit/test_news_service.py
git commit -m "feat(news): add NewsService with DDGS news fetch + LLM summarization"
```

---

## Task 5: News Streamlit Tab

**Files:**
- Modify: `src/agentic_tour_planner/app/streamlit_app.py`

**Interfaces:**
- Consumes: `NewsService.collect()`, `NewsDigest`
- Produces: New "📰 News" tab in Streamlit UI

- [ ] **Step 1: Read current streamlit_app.py structure**

Read `src/agentic_tour_planner/app/streamlit_app.py` to understand the current tab layout and session state patterns. The file is mostly commented-out legacy code — find the active `main()` function and tab structure.

- [ ] **Step 2: Add News tab to Streamlit app**

Find the active tab structure in `streamlit_app.py` and add a "📰 News" tab. The exact insertion point depends on the current active code. Based on the file content, the app appears to be in a transitional state with mostly commented code. Add the news tab as a new section.

Add the news fetching helper and tab UI:

```python
# Add at the top of the active main() function or after imports:
import asyncio
from agentic_tour_planner.services.news_service import NewsService


# Add helper function:
async def _fetch_news(destination: str, interests: list[str] | None = None):
    """Fetch news digest for a destination."""
    service = NewsService()
    return await service.collect(destination, interests)


# Add to the tab/page navigation — create a new section:
# In the sidebar navigation or tab layout, add "📰 News" option

# News tab content:
def _render_news_tab() -> None:
    st.header("📰 Recent News")
    st.caption("Fetch and summarize recent news about your destination")

    col1, col2 = st.columns([3, 1])
    with col1:
        news_dest = st.text_input(
            "Destination",
            key="news_destination",
            placeholder="e.g., Kyoto, Japan",
        )
    with col2:
        news_interests = st.text_input(
            "Interests (optional)",
            key="news_interests",
            placeholder="e.g., festivals, transport",
        )

    if st.button("Fetch News", key="fetch_news", type="primary"):
        if not news_dest:
            st.warning("Please enter a destination.")
        else:
            with st.spinner("Searching for recent news..."):
                interests = (
                    [i.strip() for i in news_interests.split(",") if i.strip()]
                    if news_interests
                    else None
                )
                digest = asyncio.run(_fetch_news(news_dest, interests))

            if digest.overview:
                st.subheader("Overview")
                st.write(digest.overview)

            if digest.articles:
                st.subheader(f"Top {len(digest.articles)} Articles")
                for article in digest.articles:
                    with st.expander(f"📰 {article.title}"):
                        st.write(
                            f"**Source:** {article.source} | **Date:** {article.date or 'Unknown'}"
                        )
                        st.write(f"**Summary:** {article.summary}")
                        st.markdown(f"[Read full article →]({article.url})")
            else:
                st.info("No recent news found for this destination.")

    if digest := st.session_state.get("last_news_digest"):
        if digest.overview:
            st.subheader("Overview")
            st.write(digest.overview)
```

- [ ] **Step 3: Wire the tab into navigation**

Find the sidebar navigation or tab structure in the active `main()` function and add `"📰 News"` as a page option. When selected, call `_render_news_tab()`.

- [ ] **Step 4: Test manually**

Run: `streamlit run src/agentic_tour_planner/app/streamlit_app.py`
Verify: News tab appears, form works, DDGS news fetches, articles display with summaries.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/app/streamlit_app.py
git commit -m "feat(ui): add News tab with DDGS news fetch and LLM summarization"
```

---

## Task 6: Run Full Test Suite

**Files:** No new files — validation only

- [ ] **Step 1: Run all unit tests**

Run: `python -m pytest tests/unit/ -v --tb=short`
Expected: All tests pass

- [ ] **Step 2: Run ruff linter**

Run: `ruff check src/agentic_tour_planner/ tests/`
Expected: No errors

- [ ] **Step 3: Run ruff formatter check**

Run: `ruff format --check src/agentic_tour_planner/ tests/`
Expected: All files formatted correctly

- [ ] **Step 4: Fix any issues found**

If linter or tests fail, fix issues and re-run.

- [ ] **Step 5: Final commit if needed**

```bash
git add -A
git commit -m "fix: address linter and test issues from DDGS tooling changes"
```

---

## Self-Review

**1. Spec coverage:** ✅
- Part 1 (Search cascade flip): Task 1
- Part 2 (DDGS images): Task 2
- Part 3 (DDGS extract): Task 3
- Part 4 (News feature): Tasks 4 + 5
- Testing: Task 6

**2. Placeholder scan:** ✅ No TBDs, no TODOs, no "implement later"

**3. Type consistency:** ✅
- `fetch_ddgs_images` returns `list[ImageCandidate]` — matches waterfall signature
- `_fetch_ddgs_extract` returns `CrawlResult | None` — matches crawler pattern
- `NewsService.collect` returns `NewsDigest` — used by Streamlit tab
- All models defined in Task 4 before being used in Task 5
