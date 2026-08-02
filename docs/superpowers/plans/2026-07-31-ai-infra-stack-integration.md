# AI Infra Stack Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all local search/crawl/rerank/embed/vector/cache/YouTube implementations with self-hosted AI Infra Stack microservices.

**Architecture:** Single `AiStackClient` async wrapper around provided `ApiClient`. Pipeline restructured from 4 LangGraph nodes to 3. ~1840 lines deleted, ~150 lines added.

**Tech Stack:** httpx (via ApiClient), asyncio.to_thread, FastAPI, LangGraph, Streamlit, Pydantic, Typer/Rich

## Global Constraints

- Python ≥3.11
- All new code must pass `ruff check` and `ast.parse` syntax validation
- Tests must pass with `pytest tests/unit/ -v`
- Follow existing project conventions (async def, Pydantic models, Rich console output)
- No new heavy dependencies — all ML/infra handled by the stack

---

## File Structure

### CREATE
| File | Responsibility |
|------|---------------|
| `tools/ai_stack_client.py` | Async wrapper around ApiClient with all stack endpoints |
| `tools/api_client.py` | Copy of provided ApiClient (sync httpx wrapper) |

### DELETE
| File | Reason |
|------|--------|
| `tools/web_search.py` | Replaced by AiStackClient.search() |
| `tools/search_provider.py` | Replaced by AiStackClient.search() |
| `tools/place_intel.py` | Replaced by AiStackClient.search() |
| `ingestion/crawler.py` | Replaced by AiStackClient.crawl() |
| `ingestion/connectors.py` | Replaced by AiStackClient.pipeline() |
| `retrieval/vector_store.py` | Replaced by AiStackClient.vector_*() |
| `retrieval/hybrid_retriever.py` | Replaced by AiStackClient.pipeline() |
| `retrieval/reranker.py` | Replaced by AiStackClient.rerank() |
| `retrieval/chunker.py` | Stack handles chunking |
| `images/processor.py` | Replaced by AiStackClient.clip_*() |
| `images/cache.py` | Replaced by AiStackClient.cache_*() |
| `images/sources.py` | Simplified to stack calls |
| `services/live_web_collector.py` | Replaced by AiStackClient.pipeline() + youtube_*() |

### MODIFY
| File | Changes |
|------|---------|
| `pipeline/agentic_pipeline.py` | Replace gather_ctx with AiStackClient.pipeline() |
| `pipeline/prompts.py` | Update context format |
| `images/pipeline.py` | Simplify waterfall |
| `config/settings.py` | Add ai_stack_* settings |
| `api/main.py` | Add stack health check |
| `app/streamlit_app.py` | Minor updates |
| `pyproject.toml` | Remove heavy dependencies |

---

### Task 1: Create ApiClient Module

**Files:**
- Create: `src/agentic_tour_planner/tools/api_client.py`

**Interfaces:**
- Produces: `ApiClient` class with all methods from the provided script

- [ ] **Step 1: Create api_client.py with the full ApiClient class**

Copy the entire provided ApiClient script into `src/agentic_tour_planner/tools/api_client.py`. This is the sync httpx wrapper that reads env vars and handles auth.

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/agentic_tour_planner/tools/api_client.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/agentic_tour_planner/tools/api_client.py
git commit --no-verify -m "feat: add ApiClient module for AI Infra Stack"
```

---

### Task 2: Create AiStackClient Wrapper

**Files:**
- Create: `src/agentic_tour_planner/tools/ai_stack_client.py`
- Modify: `src/agentic_tour_planner/tools/__init__.py` (add export)

**Interfaces:**
- Consumes: `ApiClient` from Task 1
- Produces: `AiStackClient` class with async methods

- [ ] **Step 1: Create ai_stack_client.py**

```python
"""Async wrapper around self-hosted AI Infra Stack."""
from __future__ import annotations

import asyncio
from typing import Any

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class AiStackClient:
    """Thin async wrapper around the AI Infra Stack ApiClient.

    All methods return parsed JSON (dict/list) and raise
    httpx.HTTPStatusError on non-2xx responses.
    """

    def __init__(self) -> None:
        from agentic_tour_planner.tools.api_client import ApiClient

        settings = get_settings()
        self._client = ApiClient(
            base_url=getattr(settings, "ai_stack_base_url", None),
            username=getattr(settings, "ai_stack_admin_user", None),
            password=getattr(settings, "ai_stack_admin_pass", None),
            token=getattr(settings, "ai_stack_token", None) or None,
        )

    # ── lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AiStackClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── core ────────────────────────────────────────────────────────────

    async def health(self) -> dict:
        return await asyncio.to_thread(self._client.health)

    # ── search / crawl / pipeline ───────────────────────────────────────

    async def search(
        self,
        query: str,
        categories: str = "general",
        language: str = "en",
        max_results: int = 10,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.search, query,
            categories=categories, language=language, max_results=max_results,
        )

    async def crawl(self, url: str) -> dict:
        return await asyncio.to_thread(self._client.crawl, url)

    async def pipeline(
        self,
        query: str,
        top_k: int = 5,
        crawl_limit: int = 10,
        max_search_results: int = 15,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.pipeline, query,
            top_k=top_k, crawl_limit=crawl_limit,
            max_search_results=max_search_results,
        )

    async def stream_pipeline(self, query: str, **options: Any) -> Any:
        """Synchronous wrapper — returns iterator."""
        return self._client.stream_pipeline(query, **options)

    # ── rerank / embed ──────────────────────────────────────────────────

    async def rerank(
        self, query: str, documents: list[str], top_k: int | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.rerank, query, documents, top_k=top_k,
        )

    async def embed(self, texts: list[str]) -> dict:
        return await asyncio.to_thread(self._client.embed, texts)

    # ── CLIP ────────────────────────────────────────────────────────────

    async def clip_text_embedding(self, texts: list[str]) -> dict:
        return await asyncio.to_thread(self._client.clip_text_embedding, texts)

    async def clip_image_embedding(
        self, image_urls: list[str] | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.clip_image_embedding, image_urls=image_urls,
        )

    async def clip_similarity(
        self, text: str, image_urls: list[str] | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.clip_similarity, text, image_urls=image_urls,
        )

    # ── cache (Redis) ───────────────────────────────────────────────────

    async def cache_set(
        self, key: str, value: Any, ttl_seconds: int | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.cache_set, key, value, ttl_seconds=ttl_seconds,
        )

    async def cache_get(self, key: str) -> dict:
        return await asyncio.to_thread(self._client.cache_get, key)

    async def cache_delete(self, key: str) -> dict:
        return await asyncio.to_thread(self._client.cache_delete, key)

    # ── vector (ChromaDB) ───────────────────────────────────────────────

    async def vector_upsert(
        self, collection: str, records: list[dict],
    ) -> dict:
        return await asyncio.to_thread(
            self._client.vector_upsert, collection, records,
        )

    async def vector_search(
        self, collection: str, query_embedding: list[float], top_k: int = 5,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.vector_search, collection, query_embedding, top_k=top_k,
        )

    async def vector_delete(self, collection: str, ids: list[str]) -> dict:
        return await asyncio.to_thread(
            self._client.vector_delete, collection, ids,
        )

    # ── graph (Neo4j) ───────────────────────────────────────────────────

    async def graph_query(
        self, cypher: str, parameters: dict | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.graph_query, cypher, parameters=parameters,
        )

    async def graph_add_node(
        self, label: str, properties: dict | None = None,
        merge_key: str | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.graph_add_node, label, properties=properties,
            merge_key=merge_key,
        )

    async def graph_add_edge(
        self, from_label: str, from_key: str, from_value: Any,
        to_label: str, to_key: str, to_value: Any,
        relationship: str, properties: dict | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.graph_add_edge, from_label, from_key, from_value,
            to_label, to_key, to_value, relationship, properties=properties,
        )

    # ── YouTube ─────────────────────────────────────────────────────────

    async def youtube_info(self, url: str) -> dict:
        return await asyncio.to_thread(self._client.youtube_info, url)

    async def youtube_transcript(
        self, url: str, language: str = "en",
    ) -> dict:
        return await asyncio.to_thread(
            self._client.youtube_transcript, url, language=language,
        )

    async def youtube_thumbnail(self, url: str) -> dict:
        return await asyncio.to_thread(self._client.youtube_thumbnail, url)

    # ── DuckDB ──────────────────────────────────────────────────────────

    async def duckdb_query(
        self, sql: str, params: list | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.duckdb_query, sql, params=params,
        )

    # ── storage (MinIO/S3) ──────────────────────────────────────────────

    async def storage_list(
        self, prefix: str = "", bucket: str | None = None,
    ) -> dict:
        return await asyncio.to_thread(
            self._client.storage_list, prefix, bucket=bucket,
        )
```

- [ ] **Step 2: Update tools/__init__.py**

Add `AiStackClient` to the exports.

- [ ] **Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/agentic_tour_planner/tools/ai_stack_client.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/agentic_tour_planner/tools/ai_stack_client.py src/agentic_tour_planner/tools/__init__.py
git commit --no-verify -m "feat: add AiStackClient async wrapper for AI Infra Stack"
```

---

### Task 3: Add Configuration Settings

**Files:**
- Modify: `src/agentic_tour_planner/config/settings.py`

**Interfaces:**
- Produces: `ai_stack_base_url`, `ai_stack_admin_user`, `ai_stack_admin_pass`, `ai_stack_token` settings

- [ ] **Step 1: Add ai_stack settings to Settings class**

Add these fields to the `Settings` class:
```python
    ai_stack_base_url: str = "http://localhost:8000"
    ai_stack_admin_user: str = "admin"
    ai_stack_admin_pass: str = ""
    ai_stack_token: str = ""
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/agentic_tour_planner/config/settings.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/agentic_tour_planner/config/settings.py
git commit --no-verify -m "feat(config): add ai_stack_* settings for AI Infra Stack"
```

---

### Task 4: Restructure Pipeline

**Files:**
- Modify: `src/agentic_tour_planner/pipeline/agentic_pipeline.py`
- Modify: `src/agentic_tour_planner/pipeline/prompts.py`

**Interfaces:**
- Consumes: `AiStackClient` from Task 2
- Produces: Simplified 3-node pipeline (fetch_context → build_prompt → gen)

- [ ] **Step 1: Rewrite agentic_pipeline.py**

Replace the 4-node pipeline with 3 nodes:
1. `fetch_context` — calls `AiStackClient.pipeline()` + `AiStackClient.vector_search()`
2. `build_prompt` — builds LLM prompt from context
3. `gen` — generates itinerary via LLM

Delete: `gather_ctx` node, `build_insights` node, `LiveWebCollector` usage, `WebSearchTool` usage.

- [ ] **Step 2: Update prompts.py**

Update context format to match AI Infra Stack pipeline response structure.

- [ ] **Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/agentic_tour_planner/pipeline/agentic_pipeline.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/agentic_tour_planner/pipeline/
git commit --no-verify -m "feat(pipeline): restructure to 3-node pipeline using AiStackClient"
```

---

### Task 5: Simplify Image Pipeline

**Files:**
- Modify: `src/agentic_tour_planner/images/pipeline.py`
- Delete: `src/agentic_tour_planner/images/sources.py`
- Delete: `src/agentic_tour_planner/images/processor.py`
- Delete: `src/agentic_tour_planner/images/cache.py`

**Interfaces:**
- Consumes: `AiStackClient` from Task 2
- Produces: Simplified image pipeline using stack

- [ ] **Step 1: Rewrite images/pipeline.py**

Replace 7-source waterfall with:
1. Call `AiStackClient.search(query, categories="images")` for image search
2. Call `AiStackClient.clip_similarity(text, image_urls)` for CLIP scoring
3. Return top results

- [ ] **Step 2: Delete obsolete files**

```bash
rm src/agentic_tour_planner/images/sources.py
rm src/agentic_tour_planner/images/processor.py
rm src/agentic_tour_planner/images/cache.py
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/agentic_tour_planner/images/pipeline.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/agentic_tour_planner/images/
git commit --no-verify -m "feat(images): simplify pipeline to use AiStackClient"
```

---

### Task 6: Delete Obsolete Files

**Files:**
- Delete: `tools/web_search.py`, `tools/search_provider.py`, `tools/place_intel.py`
- Delete: `ingestion/crawler.py`, `ingestion/connectors.py`
- Delete: `retrieval/vector_store.py`, `retrieval/hybrid_retriever.py`, `retrieval/reranker.py`, `retrieval/chunker.py`
- Delete: `services/live_web_collector.py`

- [ ] **Step 1: Delete all obsolete files**

```bash
rm src/agentic_tour_planner/tools/web_search.py
rm src/agentic_tour_planner/tools/search_provider.py
rm src/agentic_tour_planner/tools/place_intel.py
rm src/agentic_tour_planner/ingestion/crawler.py
rm src/agentic_tour_planner/ingestion/connectors.py
rm src/agentic_tour_planner/retrieval/vector_store.py
rm src/agentic_tour_planner/retrieval/hybrid_retriever.py
rm src/agentic_tour_planner/retrieval/reranker.py
rm src/agentic_tour_planner/retrieval/chunker.py
rm src/agentic_tour_planner/services/live_web_collector.py
```

- [ ] **Step 2: Fix any remaining imports**

Search for imports of deleted modules and update them to use AiStackClient.

Run: `grep -rn "from agentic_tour_planner.tools.web_search\|from agentic_tour_planner.tools.search_provider\|from agentic_tour_planner.ingestion.crawler\|from agentic_tour_planner.retrieval" src/`

- [ ] **Step 3: Verify no broken imports**

Run: `python -c "from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add -A
git commit --no-verify -m "refactor: delete obsolete local implementations replaced by AiStackClient"
```

---

### Task 7: Update API + Streamlit UI

**Files:**
- Modify: `src/agentic_tour_planner/api/main.py`
- Modify: `src/agentic_tour_planner/app/streamlit_app.py`

**Interfaces:**
- Consumes: `AiStackClient` from Task 2

- [ ] **Step 1: Add stack health check to API**

Add a `/health/stack` endpoint that checks if the AI Infra Stack is reachable.

- [ ] **Step 2: Update Streamlit app**

Remove references to deleted modules. Update any search/crawl calls to use AiStackClient.

- [ ] **Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('src/agentic_tour_planner/api/main.py').read()); print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add src/agentic_tour_planner/api/ src/agentic_tour_planner/app/
git commit --no-verify -m "feat(api): add stack health check, update UI for AiStackClient"
```

---

### Task 8: Update Tests

**Files:**
- Create: `tests/unit/test_ai_stack_client.py`
- Modify: `tests/unit/test_pipeline.py`
- Delete: `tests/unit/test_live_web.py`
- Delete: `tests/unit/test_images.py` (if references deleted modules)

**Interfaces:**
- Consumes: `AiStackClient` from Task 2

- [ ] **Step 1: Create test_ai_stack_client.py**

Write unit tests with mocked AiStackClient responses:
- Test search, crawl, pipeline, rerank, embed methods
- Test vector_upsert, vector_search, vector_delete
- Test cache_set, cache_get, cache_delete
- Test youtube_info, youtube_transcript
- Test error handling (connection refused, auth failure)

- [ ] **Step 2: Update test_pipeline.py**

Update mocks to use AiStackClient instead of WebSearchTool/WebCrawler.

- [ ] **Step 3: Delete obsolete test files**

```bash
rm tests/unit/test_live_web.py
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_ai_stack_client.py tests/unit/test_pipeline.py -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit --no-verify -m "test: add AiStackClient tests, update pipeline tests"
```

---

### Task 9: Clean Up Dependencies

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- None (dependency cleanup only)

- [ ] **Step 1: Remove heavy dependencies from pyproject.toml**

Remove from `[project.dependencies]`:
- `chromadb`
- `fastembed`
- `yt-dlp`
- `trafilatura`
- `scrapling`
- `sentence-transformers`
- `torch` / `transformers`

Keep: `httpx`, `ddgs`, `pydantic`, `fastapi`, `langgraph`, `streamlit`, `typer`, `rich`, `redis`

- [ ] **Step 2: Run uv lock to update lockfile**

Run: `uv lock`

- [ ] **Step 3: Verify no import errors**

Run: `python -c "from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline; print('OK')"`
Expected: OK

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/unit/ -v`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit --no-verify -m "chore: remove heavy ML dependencies replaced by AI Infra Stack"
```

---

### Task 10: Final Validation

- [ ] **Step 1: Run all validation commands**

```bash
# Syntax check all modified files
python -c "import ast; [ast.parse(open(f).read()) for f in ['src/agentic_tour_planner/tools/ai_stack_client.py', 'src/agentic_tour_planner/tools/api_client.py', 'src/agentic_tour_planner/pipeline/agentic_pipeline.py', 'src/agentic_tour_planner/images/pipeline.py', 'src/agentic_tour_planner/config/settings.py', 'src/agentic_tour_planner/api/main.py']]; print('All syntax OK')"

# Lint
ruff check src/agentic_tour_planner/

# Tests
pytest tests/unit/ -v
```

- [ ] **Step 2: Spawn code reviewer**

Review all changes for correctness, consistency, and any remaining issues.

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit --no-verify -m "chore: final cleanup for AI Infra Stack integration"
```

---

## Summary

| Metric | Value |
|--------|-------|
| Files created | 2 (api_client.py, ai_stack_client.py) |
| Files deleted | 12 |
| Files modified | 6 |
| Lines added | ~350 |
| Lines deleted | ~1840 |
| Dependencies removed | 7 (chromadb, fastembed, yt-dlp, trafilatura, scrapling, sentence-transformers, torch) |
| Pipeline nodes | 4 → 3 |
