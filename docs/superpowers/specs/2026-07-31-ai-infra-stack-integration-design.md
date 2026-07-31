# AI Infra Stack Integration — Design Spec

**Date:** 2026-07-31
**Status:** Approved
**Scope:** Replace all local search/crawl/rerank/embed/vector/cache/YouTube implementations with self-hosted AI Infra Stack microservices.

## Goal

Integrate the self-hosted AI Infra Stack as the single backend for all infrastructure operations. Remove ~1840 lines of local implementations, ~7 heavy dependencies (ChromaDB, fastembed, yt-dlp, trafilatura, scrapling, sentence-transformers, torch), and simplify the pipeline from 4 LangGraph nodes to 3.

## Architecture

### AiStackClient Wrapper

**New file:** `src/agentic_tour_planner/tools/ai_stack_client.py`

Thin async wrapper around the provided `ApiClient` class:
- Reads credentials from env vars (`BASE_URL`, `ADMIN_USER`, `ADMIN_PASS`, `JWT_SECRET`)
- Uses `asyncio.to_thread` for sync httpx calls
- Exposes: `search`, `crawl`, `pipeline`, `rerank`, `embed`, `vector_*`, `cache_*`, `youtube_*`, `graph_*`, `clip_*`
- Auto-handles auth token refresh via `ApiClient.ensure_auth()`

```python
class AiStackClient:
    """Async wrapper around self-hosted AI Infra Stack."""

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self._client = ApiClient(
            base_url=settings.ai_stack_base_url,
            username=settings.ai_stack_admin_user,
            password=settings.ai_stack_admin_pass,
            token=settings.ai_stack_token,
        )

    async def search(self, query: str, max_results: int = 10, categories: str = "general") -> dict:
        return await asyncio.to_thread(self._client.search, query, max_results=max_results, categories=categories)

    async def crawl(self, url: str) -> dict:
        return await asyncio.to_thread(self._client.crawl, url)

    async def pipeline(self, query: str, top_k: int = 5) -> dict:
        return await asyncio.to_thread(self._client.pipeline, query, top_k=top_k)

    async def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> dict:
        return await asyncio.to_thread(self._client.rerank, query, documents, top_k=top_k)

    async def embed(self, texts: list[str]) -> dict:
        return await asyncio.to_thread(self._client.embed, texts)

    # ... vector_*, cache_*, youtube_*, graph_*, clip_* methods
```

### Pipeline Restructuring

**Current (4 nodes):**
```
gather_ctx → build_insights → build_prompt → gen
```

**New (3 nodes):**
```
fetch_context → build_prompt → gen
```

`fetch_context` does:
1. Calls `AiStackClient.pipeline(query, top_k=5)` — search + crawl + rerank in one call
2. Calls `AiStackClient.vector_search(collection, embedding, top_k=10)` for local KB
3. Merges both result sets into context

### Image, CLIP & Embedding Replacement

| Current | Stack Endpoint |
|---------|---------------|
| Image waterfall (7 sources) | `search(categories="images")` |
| CLIP scoring | `clip_similarity(text, image_urls)` |
| fastembed embeddings | `embed(texts)` |
| ChromaDB vector store | `vector_upsert/search/delete()` |
| Redis cache | `cache_set/get/delete()` |
| YouTube crawling | `youtube_transcript(url)` |
| yt_dlp downloads | `youtube_download_audio/video()` |

### Auth & Configuration

**New settings in `config/settings.py`:**
```python
class Settings(BaseSettings):
    ai_stack_base_url: str = "http://localhost:8000"
    ai_stack_admin_user: str = "admin"
    ai_stack_admin_pass: str = ""
    ai_stack_token: str = ""
```

**Environment variables:**
```
BASE_URL=http://localhost:8000
ADMIN_USER=admin
ADMIN_PASS=***
JWT_SECRET=***
```

## File Changes

### DELETE (~1840 lines)
| File | Lines | Replaced by |
|------|-------|-------------|
| `tools/web_search.py` | ~100 | `AiStackClient.search()` |
| `tools/search_provider.py` | ~280 | `AiStackClient.search()` |
| `ingestion/crawler.py` | ~130 | `AiStackClient.crawl()` |
| `retrieval/vector_store.py` | ~200 | `AiStackClient.vector_*()` |
| `retrieval/hybrid_retriever.py` | ~150 | `AiStackClient.pipeline()` |
| `retrieval/reranker.py` | ~60 | `AiStackClient.rerank()` |
| `retrieval/chunker.py` | ~40 | Stack handles chunking |
| `images/processor.py` | ~150 | `AiStackClient.clip_*()` |
| `images/cache.py` | ~50 | `AiStackClient.cache_*()` |
| `images/sources.py` | ~350 | Simplified to stack calls |
| `services/live_web_collector.py` | ~250 | `AiStackClient.pipeline()` + `youtube_*()` |
| `tools/place_intel.py` | ~80 | `AiStackClient.search()` |

### CREATE (~150 lines)
| File | Purpose |
|------|---------|
| `tools/ai_stack_client.py` | Async wrapper around ApiClient |

### MODIFY
| File | Changes |
|------|---------|
| `pipeline/agentic_pipeline.py` | Replace gather_ctx with AiStackClient.pipeline() |
| `pipeline/prompts.py` | Update context format for stack results |
| `images/pipeline.py` | Simplify waterfall to stack-first |
| `config/settings.py` | Add ai_stack_* settings |
| `api/main.py` | Add stack health check |
| `app/streamlit_app.py` | Minor updates for new pipeline |

### Dependencies to REMOVE from pyproject.toml
- `chromadb` → stack `/vector/*`
- `fastembed` → stack `/embed`
- `yt-dlp` → stack `/youtube/*`
- `trafilatura` → stack `/crawl`
- `scrapling` → stack `/crawl`
- `sentence-transformers` → stack `/embed`
- `torch` / `transformers` → stack `/clip/*`

## Testing

### New tests
- `tests/unit/test_ai_stack_client.py` — Mock AiStackClient responses, test wrapper methods

### Modified tests
- `tests/unit/test_pipeline.py` — Update mocks to use AiStackClient
- `tests/unit/test_live_web.py` — Remove or rewrite
- `tests/unit/test_images.py` — Update for stack-based image search

### Validation commands
```bash
python -c "import ast; ast.parse(open('src/...').read())"
ruff check src/agentic_tour_planner/
pytest tests/unit/ -v
```

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Stack unreachable | Health check returns degraded status; pipeline fails gracefully |
| Auth token expiry | Auto-refresh via `ApiClient.ensure_auth()` |
| Different response formats | AiStackClient normalizes responses to match existing data shapes |
| Missing stack endpoints | Feature detection at init time; log warnings for unsupported ops |
