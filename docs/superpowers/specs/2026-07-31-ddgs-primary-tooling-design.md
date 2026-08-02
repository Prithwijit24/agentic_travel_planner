# DDGS Primary Tooling — Design Spec

## Goal

Make DuckDuckGo Search (`ddgs`) the primary tool for web search, image search, video search, and content extraction, with existing paid/API backends as fallbacks. Add a new News feature that fetches, summarizes, and displays recent news about a destination in a separate Streamlit UI tab.

## Current State

| Capability | Primary | Fallback | Notes |
|------------|---------|----------|-------|
| Web search | Tavily | SerpAPI → DDGS | DDGS is last-resort |
| Video search | SerpAPI YouTube | DDGS videos | DDGS is last-resort |
| Image search | Wikidata → Wikimedia → Wikipedia → Openverse → Mapillary → Stock | — | DDGS not used |
| Content extraction | trafilatura / crawl4ai / scrapling | — | DDGS not used |
| News | — | — | Feature does not exist |

## Target State

| Capability | Primary | Fallback 1 | Fallback 2 |
|------------|---------|------------|------------|
| Web search | **DDGS** | Tavily | SerpAPI |
| Video search | **DDGS videos** | SerpAPI YouTube | — |
| Image search | **DDGS images** | Wikidata → Wikimedia → Wikipedia → Openverse → Mapillary → Stock |
| Content extraction | **DDGS extract** | trafilatura → scrapling → crawl4ai |
| News | **DDGS news** → LLM summarize | — | — |

## Part 1: Search Cascade Flip

### Files to Change

- `src/agentic_tour_planner/tools/web_search.py`
- `src/agentic_tour_planner/tools/search_provider.py`

### Design

Flip the cascade tuple order in both files so DDGS runs first:

**`web_search.py` — `WebSearchTool.search()`:**
```python
# Before:
("tavily", self._search_tavily),
("serpapi", self._search_serpapi),
("ddgs", self._search_ddgs),

# After:
("ddgs", self._search_ddgs),
("tavily", self._search_tavily),
("serpapi", self._search_serpapi),
```

**`search_provider.py` — `SearchProvider.search()`:**

For `kind="web"`:
```python
# Before:
("tavily", self._search_tavily),
("serpapi", self._search_serpapi),
("ddgs", self._search_ddgs),

# After:
("ddgs", self._search_ddgs),
("tavily", self._search_tavily),
("serpapi", self._search_serpapi),
```

For `kind="video"`:
```python
# Before:
("serpapi", self._search_serpapi),
("ddgs", self._search_ddgs),

# After:
("ddgs", self._search_ddgs),
("serpapi", self._search_serpapi),
```

### Behavior

- DDGS runs first (no API key needed, fast)
- If DDGS returns 0 results or raises, try Tavily (web) or SerpAPI (video)
- If second backend fails, try remaining backend
- Logging stays the same — each backend logs its attempt
- No API key changes needed — DDGS requires none

## Part 2: DDGS Images as #1 Primary

### Files to Change

- `src/agentic_tour_planner/images/sources.py` — add `fetch_ddgs_images()` function
- `src/agentic_tour_planner/images/pipeline.py` — insert at position 0 in `_WATERFALL`

### Design

**New function in `sources.py`:**
```python
async def fetch_ddgs_images(place_name: str) -> list[ImageCandidate]:
    """Search DuckDuckGo for images of a place."""
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

**Pipeline change in `pipeline.py`:**
```python
_WATERFALL = [
    (fetch_ddgs_images, False),    # NEW — #1 primary
    (fetch_wikidata, False),       # was #1
    (fetch_wikimedia_commons, False),
    (fetch_wikipedia, False),
    (fetch_openverse, False),
    (fetch_mapillary, True),
    (fetch_stock, False),
]
```

### Behavior

- DDGS images runs first for every place — no API key needed
- Returns real web images immediately with URL, dimensions, source
- No license info from DDGS — `verified=False`, `license=None`
- Falls back to existing structured sources (Wikidata, Wikimedia, etc.) for better licensing/attribution
- Existing CLIP scoring, dedup, NSFW moderation still apply to all candidates

## Part 3: DDGS Extract as First Fallback

### Files to Change

- `src/agentic_tour_planner/ingestion/crawler.py` — add `_fetch_ddgs_extract()` method

### Design

**New method in `WebCrawler`:**
```python
async def _fetch_ddgs_extract(self, url: str) -> CrawlResult | None:
    """Fast content extraction via DDGS().extract()."""
    try:
        from ddgs import DDGS
        items = list(DDGS().extract(url))
        if not items:
            return None
        # DDGS extract returns list of dicts with 'title' and 'content'
        content = "\n\n".join(item.get("content", "") for item in items if item.get("content"))
        title = items[0].get("title", "") if items else ""
        if not content.strip():
            return None
        return CrawlResult(
            url=url,
            title=title,
            content=content[:self._MAX_CONTENT_CHARS],
            metadata={"backend": "ddgs_extract"},
        )
    except Exception as exc:
        logger.debug(f"DDGS extract failed for {url}: {exc}")
        return None
```

**Modified `fetch()` method:**
```python
async def fetch(self, url: str, backend: str | None = None) -> CrawlResult:
    # Try DDGS extract first (fast, no API key)
    ddgs_result = await self._fetch_ddgs_extract(url)
    if ddgs_result and ddgs_result.content.strip():
        return ddgs_result

    # Fall back to existing cascade
    resolved_backend = backend or self.settings.web_crawl_backend
    # ... existing logic unchanged
```

### Behavior

- DDGS extract runs first for every URL — fast, no API key
- Returns cleaned text content with title
- If DDGS returns empty or fails, falls through to existing WebCrawler cascade
- No proxy support, no browser rendering — just fast text extraction
- Existing Redis caching, proxy routing, crawl4ai/scrapling all preserved

## Part 4: News Feature

### New Files

- `src/agentic_tour_planner/services/news_service.py` — `NewsService` class

### Modified Files

- `src/agentic_tour_planner/app/streamlit_app.py` — add "📰 News" tab

### Domain Models

```python
# In news_service.py (or domain/models.py if preferred)

class NewsArticle(BaseModel):
    title: str
    url: str
    source: str
    date: str | None = None
    snippet: str          # raw from DDGS
    summary: str = ""     # LLM-generated 1-2 sentence summary

class NewsDigest(BaseModel):
    destination: str
    overview: str         # LLM 3-5 sentence overview
    articles: list[NewsArticle]
    fetched_at: str
```

### `NewsService` Design

```python
class NewsService:
    """Fetch and summarize recent news about a destination using DDGS."""

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm or LLMProvider()
        self.cache = RedisCache()

    async def collect(
        self,
        destination: str,
        interests: list[str] | None = None,
    ) -> NewsDigest:
        """Fetch news, deduplicate, LLM-summarize, cache."""
        cache_key = f"news:{destination}"

        # Check cache (1 hour TTL)
        cached = await self.cache.get_json(cache_key)
        if cached:
            return NewsDigest(**cached)

        # Fetch from DDGS
        topics = ", ".join(interests) if interests else ""
        query = f"{destination} {topics}".strip()
        raw = list(DDGS().news(query, max_results=10, timelimit="m"))

        # Deduplicate by URL
        articles = []
        seen_urls: set[str] = set()
        for item in raw:
            url = item.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            articles.append(NewsArticle(
                title=item.get("title", ""),
                url=url,
                source=item.get("source", ""),
                date=item.get("date"),
                snippet=item.get("body", ""),
            ))

        if not articles:
            return NewsDigest(destination=destination, overview="No recent news found.", articles=[])

        # LLM summarization
        overview = await self._summarize_overview(destination, articles)
        for article in articles:
            article.summary = await self._summarize_article(article)

        digest = NewsDigest(
            destination=destination,
            overview=overview,
            articles=articles[:5],  # Cap at 5 articles
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

        # Cache for 1 hour
        await self.cache.set_json(cache_key, digest.model_dump(), ttl=3600)
        return digest

    async def _summarize_overview(self, destination: str, articles: list[NewsArticle]) -> str:
        """LLM generates a 3-5 sentence overview of what's happening."""
        headlines = "\n".join(f"- {a.title} ({a.source})" for a in articles[:10])
        prompt = (
            f"Recent news about {destination}:\n{headlines}\n\n"
            f"Write a 3-5 sentence overview of what's currently happening in {destination}. "
            f"Be factual and concise."
        )
        return await self.llm.complete_json(prompt, role="worker")

    async def _summarize_article(self, article: NewsArticle) -> str:
        """LLM generates a 1-2 sentence summary from headline + snippet."""
        prompt = (
            f"Title: {article.title}\n"
            f"Source: {article.source}\n"
            f"Snippet: {article.snippet}\n\n"
            f"Write a 1-2 sentence factual summary of this news article."
        )
        return await self.llm.complete_json(prompt, role="worker")
```

### Streamlit UI — New "📰 News" Tab

```python
# In streamlit_app.py — add to the tab layout

# Tab 4: News
with tab_news:
    st.header("📰 Recent News")
    st.caption("Fetch and summarize recent news about your destination")

    col1, col2 = st.columns([3, 1])
    with col1:
        news_dest = st.text_input(
            "Destination",
            key="news_destination",
            placeholder="e.g., Kyoto, Japan"
        )
    with col2:
        news_interests = st.text_input(
            "Interests (optional)",
            key="news_interests",
            placeholder="e.g., festivals, transport"
        )

    if st.button("Fetch News", key="fetch_news"):
        if not news_dest:
            st.warning("Please enter a destination.")
        else:
            with st.spinner("Searching for recent news..."):
                interests = [i.strip() for i in news_interests.split(",") if i.strip()] or None
                digest = asyncio.run(_fetch_news(news_dest, interests))

            if digest.overview:
                st.subheader("Overview")
                st.write(digest.overview)

            if digest.articles:
                st.subheader(f"Top {len(digest.articles)} Articles")
                for article in digest.articles:
                    with st.expander(f"📰 {article.title}"):
                        st.write(f"**Source:** {article.source} | **Date:** {article.date or 'Unknown'}")
                        st.write(f"**Summary:** {article.summary}")
                        st.write(f"[Read full article →]({article.url})")
            else:
                st.info("No recent news found for this destination.")
```

## Error Handling

- All DDGS calls wrapped in try/except — failures never crash the pipeline
- DDGS rate limiting: `ddgs` package handles this internally with backoff
- News caching prevents repeated DDGS calls for the same destination
- LLM summarization failures fall back to raw snippets

## Testing

- Unit tests for each new/modified method
- Test cascade order (DDGS → Tavily → SerpAPI)
- Test DDGS image waterfall position
- Test DDGS extract fallback to WebCrawler
- Test NewsService with mocked DDGS responses
- Test Streamlit tab renders correctly
- Existing tests must continue to pass

## Non-Goals

- No changes to API endpoints — news is Streamlit-only for now
- No removal of existing backends — all kept as fallbacks
- No rate limiting beyond DDGS built-in — can add later if needed
- No news ingestion into knowledge base — live-only
