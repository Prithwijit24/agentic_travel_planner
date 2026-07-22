# API Streaming & UI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the Streamlit UI to FastAPI with Pydantic-validated responses, add SSE streaming for live progress logs, and a separate image endpoint.

**Architecture:** Dual-endpoint approach: `POST /plans` returns validated `PlanAPIResponse`, `GET /plans/stream/{request_id}` streams `LogEvent` SSE, `GET /plans/{plan_id}/images` resolves image queries to URLs.

**Tech Stack:** FastAPI, SSE-Starlette, httpx, Pydantic, Streamlit, sse-starlette

## Global Constraints

- Python 3.11+, FastAPI, Pydantic v2
- API base URL from `API_BASE_URL` environment variable
- CORS already configured with `allow_origins=["*"]`
- Existing `PlanningResponse` model unchanged (wrapped by new `PlanAPIResponse`)
- CLI, ingestion, evaluation, retrieval modules NOT modified

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/agentic_tour_planner/domain/models.py` | Add `LogEvent`, `PlanAPIResponse`, `PlaceImage`, `ImageResponse`, `image_query` to `SpotDetail` |
| `src/agentic_tour_planner/api/events.py` | `EventEmitter` class + in-memory registry for SSE |
| `src/agentic_tour_planner/api/images.py` | Image resolution endpoint (Unsplash/Pexels) |
| `src/agentic_tour_planner/api/main.py` | Modify `POST /plans` to return `PlanAPIResponse`, add SSE endpoint, add images endpoint |
| `src/agentic_tour_planner/pipeline/agentic_pipeline.py` | Emit `LogEvent` during pipeline execution |
| `src/agentic_tour_planner/app/streamlit_app.py` | Connect to API, consume SSE, display live logs + images |
| `tests/unit/test_events.py` | Tests for EventEmitter |
| `tests/unit/test_api_streaming.py` | Tests for SSE endpoint |
| `tests/unit/test_images.py` | Tests for image endpoint |

---

### Task 1: Add Pydantic Models

**Files:**
- Modify: `src/agentic_tour_planner/domain/models.py:154-161` (SpotDetail)
- Modify: `src/agentic_tour_planner/domain/models.py:1` (imports)
- Test: `tests/unit/test_models.py`

**Interfaces:**
- Consumes: existing `SpotDetail`, `PlanningResponse`
- Produces: `LogEvent`, `PlanAPIResponse`, `PlaceImage`, `ImageResponse`, updated `SpotDetail`

- [ ] **Step 1: Add `image_query` to `SpotDetail`**

```python
class SpotDetail(BaseModel):
    name: str
    slot: str | None = None
    history: str | None = None
    opening_hours: str | None = None
    closing_hours: str | None = None
    best_time: str | None = None
    description: str | None = None
    image_query: str | None = None  # LLM-generated search term for images
```

- [ ] **Step 2: Add new models at end of `domain/models.py`**

```python
from typing import Literal

class LogEvent(BaseModel):
    """A single event in the SSE stream."""
    event: Literal["step", "debug", "metric", "error", "done"]
    step: str | None = None
    message: str
    detail: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PlanAPIResponse(BaseModel):
    """Validated response the UI maps from."""
    request_id: str
    plan: PlanningResponse
    status: Literal["completed", "error"]
    error: str | None = None


class PlaceImage(BaseModel):
    place_name: str
    image_query: str
    image_url: str | None = None
    source: str | None = None


class ImageResponse(BaseModel):
    plan_id: str
    images: list[PlaceImage]
```

- [ ] **Step 3: Run existing model tests to verify no breakage**

Run: `pytest tests/unit/test_models.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agentic_tour_planner/domain/models.py
git commit -m "feat: add LogEvent, PlanAPIResponse, PlaceImage, ImageResponse models; add image_query to SpotDetail"
```

---

### Task 2: Create EventEmitter

**Files:**
- Create: `src/agentic_tour_planner/api/events.py`
- Test: `tests/unit/test_events.py`

**Interfaces:**
- Consumes: `LogEvent` from Task 1
- Produces: `EventEmitter`, `register_emitter`, `get_emitter`, `remove_emitter`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_events.py
import asyncio
import pytest
from agentic_tour_planner.api.events import EventEmitter, register_emitter, get_emitter, remove_emitter
from agentic_tour_planner.domain.models import LogEvent


@pytest.mark.asyncio
async def test_event_emitter_streams_events():
    emitter = EventEmitter()
    emitter.emit(LogEvent(event="step", message="Gathering context..."))
    emitter.emit(LogEvent(event="done", message="Complete"))

    events = []
    async for event in emitter.stream():
        events.append(event)

    assert len(events) == 2
    assert events[0].event == "step"
    assert events[1].event == "done"


@pytest.mark.asyncio
async def test_event_emitter_stops_at_done():
    emitter = EventEmitter()
    emitter.emit(LogEvent(event="step", message="Step 1"))
    emitter.emit(LogEvent(event="debug", message="Details"))
    emitter.emit(LogEvent(event="done", message="Done"))

    events = []
    async for event in emitter.stream():
        events.append(event)

    assert len(events) == 3
    assert events[-1].event == "done"


def test_register_and_get_emitter():
    emitter = EventEmitter()
    register_emitter("req-123", emitter)
    assert get_emitter("req-123") is emitter
    remove_emitter("req-123")
    assert get_emitter("req-123") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_events.py -v`
Expected: FAIL with "cannot import name 'EventEmitter'"

- [ ] **Step 3: Write the implementation**

```python
# src/agentic_tour_planner/api/events.py
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from agentic_tour_planner.domain.models import LogEvent
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_emitters: dict[str, EventEmitter] = {}


class EventEmitter:
    """Collects log events during pipeline execution for SSE streaming."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[LogEvent] = asyncio.Queue()

    def emit(self, event: LogEvent) -> None:
        self._queue.put_nowait(event)
        logger.debug("EventEmitter.emit event={} message={}", event.event, event.message)

    async def stream(self) -> AsyncIterator[LogEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.event == "done":
                break


def register_emitter(request_id: str, emitter: EventEmitter) -> None:
    _emitters[request_id] = emitter
    logger.debug("register_emitter request_id={}", request_id)


def get_emitter(request_id: str) -> EventEmitter | None:
    return _emitters.get(request_id)


def remove_emitter(request_id: str) -> None:
    _emitters.pop(request_id, None)
    logger.debug("remove_emitter request_id={}", request_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/api/events.py tests/unit/test_events.py
git commit -m "feat: add EventEmitter for SSE streaming with registry"
```

---

### Task 3: Modify POST /plans to Return PlanAPIResponse

**Files:**
- Modify: `src/agentic_tour_planner/api/main.py:54-67`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `PlanAPIResponse` from Task 1, `EventEmitter` from Task 2
- Produces: modified `create_plan` endpoint returning `PlanAPIResponse`

- [ ] **Step 1: Update imports in `api/main.py`**

Add to imports:
```python
from uuid import uuid4
from agentic_tour_planner.domain.models import PlanAPIResponse
from agentic_tour_planner.api.events import EventEmitter, register_emitter, remove_emitter
```

- [ ] **Step 2: Modify `create_plan` endpoint**

```python
@app.post("/plans", response_model=PlanAPIResponse)
async def create_plan(request: PlanningRequest) -> PlanAPIResponse:
    logger.info(f"POST /plans destination={request.destination} provider={request.provider or 'default'}")
    request_id = str(uuid4())
    pipeline = AgenticTourPlannerPipeline()
    store = SQLitePlanStore()
    provider = (request.provider or settings.default_llm_provider) or "unknown"
    REQUEST_COUNT.labels(endpoint="/plans", provider=provider).inc()
    start = time.perf_counter()
    try:
        response = await pipeline.run(request)
        store.save_plan(request, response)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.info(f"POST /plans completed plan_id={response.plan_id} in {elapsed:.2f}s")
        return PlanAPIResponse(
            request_id=request_id,
            plan=response,
            status="completed",
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.error(f"POST /plans failed in {elapsed:.2f}s: {e}")
        return PlanAPIResponse(
            request_id=request_id,
            plan=None,  # type: ignore
            status="error",
            error=str(e),
        )
```

- [ ] **Step 3: Update existing API tests to expect `PlanAPIResponse`**

```python
# In tests/integration/test_api.py, update assertions:
# Old: assert "plan_id" in response.json()
# New: assert response.json()["status"] == "completed"
#      assert "plan_id" in response.json()["plan"]
```

- [ ] **Step 4: Run API tests**

Run: `pytest tests/integration/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/api/main.py tests/integration/test_api.py
git commit -m "feat: POST /plans now returns PlanAPIResponse with request_id"
```

---

### Task 4: Add SSE Streaming Endpoint

**Files:**
- Modify: `src/agentic_tour_planner/api/main.py` (add endpoint)
- Modify: `pyproject.toml` (add sse-starlette dependency)
- Test: `tests/unit/test_api_streaming.py`

**Interfaces:**
- Consumes: `EventEmitter`, `register_emitter`, `get_emitter`, `remove_emitter` from Task 2
- Produces: `GET /plans/stream/{request_id}` endpoint

- [ ] **Step 1: Add `sse-starlette` dependency**

```bash
uv add sse-starlette
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_api_streaming.py
import pytest
from httpx import AsyncClient, ASGITransport
from agentic_tour_planner.api.main import app
from agentic_tour_planner.api.events import EventEmitter, register_emitter
from agentic_tour_planner.domain.models import LogEvent


@pytest.mark.asyncio
async def test_stream_endpoint_returns_events():
    emitter = EventEmitter()
    emitter.emit(LogEvent(event="step", message="Gathering context..."))
    emitter.emit(LogEvent(event="done", message="Complete"))
    register_emitter("test-req-1", emitter)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/plans/stream/test-req-1")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_api_streaming.py -v`
Expected: FAIL with 404

- [ ] **Step 4: Add SSE endpoint to `api/main.py`**

```python
from sse_starlette.sse import EventSourceResponse
from agentic_tour_planner.api.events import get_emitter, remove_emitter

@app.get("/plans/stream/{request_id}")
async def stream_plan(request_id: str):
    logger.info(f"GET /plans/stream/{request_id}")
    emitter = get_emitter(request_id)
    if emitter is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Stream not found")

    async def event_generator():
        try:
            async for event in emitter.stream():
                yield {
                    "event": event.event,
                    "data": event.model_dump_json(),
                }
        finally:
            remove_emitter(request_id)

    return EventSourceResponse(event_generator())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_api_streaming.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/api/main.py pyproject.toml tests/unit/test_api_streaming.py
git commit -m "feat: add SSE streaming endpoint GET /plans/stream/{request_id}"
```

---

### Task 5: Emit LogEvents from Pipeline

**Files:**
- Modify: `src/agentic_tour_planner/pipeline/agentic_pipeline.py` (add emitter parameter to `run`)
- Modify: `src/agentic_tour_planner/api/main.py` (wire emitter into pipeline call)

**Interfaces:**
- Consumes: `EventEmitter`, `LogEvent` from Tasks 1-2
- Produces: pipeline emits `LogEvent` at each step

- [ ] **Step 1: Add optional `emitter` parameter to pipeline `run` method**

In `agentic_pipeline.py`, modify the `run` method signature:

```python
async def run(
    self,
    request: PlanningRequest,
    context: RetrievedContext | None = None,
    insights: PlanningInsights | None = None,
    emitter: EventEmitter | None = None,
) -> PlanningResponse:
```

Add emit calls at each step:

```python
if emitter:
    emitter.emit(LogEvent(event="step", step="Gather Context", message="Gathering context..."))

# ... existing gather_context code ...

if emitter:
    emitter.emit(LogEvent(event="debug", step="Gather Context", message="Context gathered", detail={
        "documents_count": len(context.documents),
        "search_results_count": len(context.search_results),
        "place_hours_count": len(context.place_hours),
    }))

if emitter:
    emitter.emit(LogEvent(event="step", step="Build Insights", message="Building insights..."))

# ... existing insights code ...

if emitter:
    emitter.emit(LogEvent(event="debug", step="Build Insights", message="Insights built", detail={
        "route_strategy_preview": insights.route.strategy[:80],
        "budget_estimate": insights.budget.estimated_daily_budget,
    }))

if emitter:
    emitter.emit(LogEvent(event="step", step="Generate Plan", message="Generating plan..."))

# ... existing plan generation ...

if emitter:
    emitter.emit(LogEvent(event="metric", step="Generate Plan", message="Plan generated", detail={
        "provider": response.provider_used,
        "model": response.model_used,
    }))
```

- [ ] **Step 2: Wire emitter into `create_plan` endpoint**

In `api/main.py`, modify `create_plan`:

```python
@app.post("/plans", response_model=PlanAPIResponse)
async def create_plan(request: PlanningRequest) -> PlanAPIResponse:
    logger.info(f"POST /plans destination={request.destination} provider={request.provider or 'default'}")
    request_id = str(uuid4())
    emitter = EventEmitter()
    register_emitter(request_id, emitter)
    pipeline = AgenticTourPlannerPipeline()
    store = SQLitePlanStore()
    provider = (request.provider or settings.default_llm_provider) or "unknown"
    REQUEST_COUNT.labels(endpoint="/plans", provider=provider).inc()
    start = time.perf_counter()
    try:
        response = await pipeline.run(request, emitter=emitter)
        store.save_plan(request, response)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.info(f"POST /plans completed plan_id={response.plan_id} in {elapsed:.2f}s")
        emitter.emit(LogEvent(event="done", message="Plan complete", detail={"plan_id": response.plan_id, "status": "completed"}))
        return PlanAPIResponse(
            request_id=request_id,
            plan=response,
            status="completed",
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.error(f"POST /plans failed in {elapsed:.2f}s: {e}")
        emitter.emit(LogEvent(event="error", message=str(e)))
        emitter.emit(LogEvent(event="done", message="Plan failed", detail={"status": "error"}))
        return PlanAPIResponse(
            request_id=request_id,
            plan=None,  # type: ignore
            status="error",
            error=str(e),
        )
```

- [ ] **Step 3: Run existing tests to verify no breakage**

Run: `pytest tests/ -v --ignore=tests/unit/test_api_streaming.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agentic_tour_planner/pipeline/agentic_pipeline.py src/agentic_tour_planner/api/main.py
git commit -m "feat: emit LogEvents from pipeline during execution"
```

---

### Task 6: Create Image Endpoint

**Files:**
- Create: `src/agentic_tour_planner/api/images.py`
- Modify: `src/agentic_tour_planner/api/main.py` (register router)
- Modify: `src/agentic_tour_planner/config/settings.py` (add image API keys)
- Test: `tests/unit/test_images.py`

**Interfaces:**
- Consumes: `PlaceImage`, `ImageResponse` from Task 1
- Produces: `GET /plans/{plan_id}/images` endpoint

- [ ] **Step 1: Add image API settings**

```python
# In config/settings.py, add to Settings class:
unsplash_access_key: str | None = None
pexels_api_key: str | None = None
image_provider: str = "unsplash"  # "unsplash" | "pexels"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_images.py
import pytest
from unittest.mock import patch, AsyncMock
from agentic_tour_planner.api.images import resolve_images
from agentic_tour_planner.domain.models import PlaceImage


@pytest.mark.asyncio
async def test_resolve_images_returns_urls():
    places = [
        {"place_name": "Fushimi Inari", "image_query": "fushimi inari shrine kyoto"},
        {"place_name": "Kinkaku-ji", "image_query": "golden pavilion kyoto"},
    ]

    with patch("agentic_tour_planner.api.images._fetch_unsplash", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = "https://images.unsplash.com/test.jpg"
        result = await resolve_images(places)

    assert len(result) == 2
    assert all(isinstance(img, PlaceImage) for img in result)
    assert result[0].image_url == "https://images.unsplash.com/test.jpg"
    assert result[0].source == "unsplash"


@pytest.mark.asyncio
async def test_resolve_images_handles_failure():
    places = [{"place_name": "Test", "image_query": "test query"}]

    with patch("agentic_tour_planner.api.images._fetch_unsplash", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None
        result = await resolve_images(places)

    assert len(result) == 1
    assert result[0].image_url is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_images.py -v`
Expected: FAIL with "cannot import name 'resolve_images'"

- [ ] **Step 4: Write the implementation**

```python
# src/agentic_tour_planner/api/images.py
from __future__ import annotations

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import ImageResponse, PlaceImage
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


async def _fetch_unsplash(query: str) -> str | None:
    settings = get_settings()
    if not settings.unsplash_access_key:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 1},
                headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
                timeout=10,
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            if results:
                return results[0]["urls"]["regular"]
    except Exception as exc:
        logger.warning(f"Unsplash search failed for {query!r}: {exc}")
    return None


async def _fetch_pexels(query: str) -> str | None:
    settings = get_settings()
    if not settings.pexels_api_key:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 1},
                headers={"Authorization": settings.pexels_api_key},
                timeout=10,
            )
            r.raise_for_status()
            photos = r.json().get("photos", [])
            if photos:
                return photos[0]["src"]["large"]
    except Exception as exc:
        logger.warning(f"Pexels search failed for {query!r}: {exc}")
    return None


async def resolve_images(places: list[dict]) -> list[PlaceImage]:
    settings = get_settings()
    results = []
    for place in places:
        query = place.get("image_query", "")
        name = place.get("place_name", "")

        if settings.image_provider == "pexels":
            url = await _fetch_pexels(query)
            source = "pexels"
        else:
            url = await _fetch_unsplash(query)
            source = "unsplash"

        results.append(PlaceImage(
            place_name=name,
            image_query=query,
            image_url=url,
            source=source if url else None,
        ))
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_images.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/api/images.py src/agentic_tour_planner/config/settings.py tests/unit/test_images.py
git commit -m "feat: add image resolution endpoint with Unsplash/Pexels support"
```

---

### Task 7: Register Image Router in Main App

**Files:**
- Modify: `src/agentic_tour_planner/api/main.py`
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: image router from Task 6
- Produces: `GET /plans/{plan_id}/images` available in the app

- [ ] **Step 1: Add image endpoint to `api/main.py`**

```python
from agentic_tour_planner.api.images import resolve_images

@app.get("/plans/{plan_id}/images", response_model=ImageResponse)
async def get_plan_images(plan_id: str) -> ImageResponse:
    logger.info(f"GET /plans/{plan_id}/images")
    store = SQLitePlanStore()
    record = store.get_plan(plan_id)
    if record is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Plan not found")

    places = []
    for day in record.response.itinerary:
        for spot in day.spots:
            if spot.image_query:
                places.append({"place_name": spot.name, "image_query": spot.image_query})

    images = await resolve_images(places)
    return ImageResponse(plan_id=plan_id, images=images)
```

- [ ] **Step 2: Add `get_plan` method to SQLitePlanStore if missing**

Check if `SQLitePlanStore` has a `get_plan(plan_id)` method. If not, add it:

```python
def get_plan(self, plan_id: str) -> StoredPlanRecord | None:
    conn = sqlite3.connect(self._db_path)
    cursor = conn.execute(
        "SELECT plan_id, destination, created_at, provider_used, model_used, request, response FROM plans WHERE plan_id = ?",
        (plan_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    return StoredPlanRecord(
        plan_id=row[0],
        destination=row[1],
        created_at=datetime.fromisoformat(row[2]),
        provider_used=row[3],
        model_used=row[4],
        request=PlanningRequest.model_validate_json(row[5]),
        response=PlanningResponse.model_validate_json(row[6]),
    )
```

- [ ] **Step 3: Add API test for images endpoint**

```python
# In tests/integration/test_api.py:
@pytest.mark.asyncio
async def test_get_plan_images():
    # First create a plan
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_response = await client.post("/plans", json={
            "destination": "Kyoto",
            "trip_length_days": 2,
            "interests": ["temples"],
        })
        plan_id = create_response.json()["plan"]["plan_id"]

        # Then get images
        images_response = await client.get(f"/plans/{plan_id}/images")
        assert images_response.status_code == 200
        assert images_response.json()["plan_id"] == plan_id
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/api/main.py src/agentic_tour_planner/storage/sqlite_store.py tests/integration/test_api.py
git commit -m "feat: add GET /plans/{plan_id}/images endpoint"
```

---

### Task 8: Connect Streamlit UI to API

**Files:**
- Modify: `src/agentic_tour_planner/app/streamlit_app.py`

**Interfaces:**
- Consumes: `PlanAPIResponse`, `LogEvent`, `ImageResponse` from Tasks 1-7
- Produces: UI calls API, shows live SSE logs, renders plan with images

- [ ] **Step 1: Add API client helper functions**

```python
# At top of streamlit_app.py, add imports:
import os
import httpx
from agentic_tour_planner.domain.models import PlanningRequest

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


def _build_request_from_form(...) -> PlanningRequest:
    """Convert form fields to PlanningRequest."""
    return PlanningRequest(
        destination=destination,
        origin=origin or None,
        trip_length_days=days,
        interests=[i.strip() for i in interests.split(",") if i.strip()],
        budget_level=budget,
        travel_month=month,
        notes=notes or None,
        provider=provider or None,
        places_per_day=places_per_day,
        transport_mode=transport,
        travelers=members,
        include_live_data=live,
    )


async def _call_plans_api(request: PlanningRequest) -> dict:
    """POST to /plans and return the response."""
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{API_BASE_URL}/plans", json=request.model_dump(mode="json"))
        r.raise_for_status()
        return r.json()


async def _stream_logs(request_id: str, callback) -> None:
    """Connect to SSE stream and call callback for each event."""
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("GET", f"{API_BASE_URL}/plans/stream/{request_id}") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    import json
                    event_data = json.loads(line[6:])
                    callback(event_data)


async def _fetch_images(plan_id: str) -> dict:
    """GET /plans/{plan_id}/images."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API_BASE_URL}/plans/{plan_id}/images")
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 2: Replace mock loading with API call + SSE**

Replace the form submission handler:

```python
# Old: time.sleep(10) + mock data
# New:
if st.session_state.get("form_submitted") and not st.session_state.get("is_loading") and not st.session_state.get("plan"):
    st.session_state.is_loading = True

    with main_area:
        # Progress bar
        progress = st.progress(0, text="Initializing...")

        # Build request from form
        request = _build_request_from_form(...)

        # Call API
        import asyncio
        response_data = asyncio.run(_call_plans_api(request))

        if response_data["status"] == "error":
            st.error(f"Plan generation failed: {response_data['error']}")
            st.session_state.is_loading = False
        else:
            request_id = response_data["request_id"]
            plan_data = response_data["plan"]

            # Stream logs
            step_count = 0
            total_steps = 4

            def on_event(event_data):
                nonlocal step_count
                if event_data["event"] == "step":
                    step_count += 1
                    progress.progress(step_count / total_steps, text=event_data["message"])
                elif event_data["event"] == "debug":
                    # Update terminal with debug info
                    pass
                elif event_data["event"] == "done":
                    progress.progress(1.0, text="Complete!")

            asyncio.run(_stream_logs(request_id, on_event))

            # Fetch images
            images_data = asyncio.run(_fetch_images(plan_data["plan_id"]))

            # Store in session
            st.session_state.plan = plan_data
            st.session_state.images = images_data.get("images", [])
            st.session_state.is_loading = False
            st.rerun()
```

- [ ] **Step 3: Update results page to use images**

In the results page section, when rendering spots:

```python
# When rendering each spot, check for image:
images = st.session_state.get("images", [])
spot_image = next((img for img in images if img["place_name"] == spot["name"]), None)
if spot_image and spot_image.get("image_url"):
    img_url = spot_image["image_url"]
else:
    img_url = f"https://source.unsplash.com/600x400/?{spot['name'].replace(' ', ',')}"
```

- [ ] **Step 4: Manual test — run Streamlit app**

Run: `streamlit run src/agentic_tour_planner/app/streamlit_app.py`
Verify: form submits to API, logs stream, images display

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/app/streamlit_app.py
git commit -m "feat: connect Streamlit UI to FastAPI with SSE streaming and images"
```

---

### Task 9: Add Environment Variables to .env.example

**Files:**
- Modify: `.env.example` (or create if missing)

- [ ] **Step 1: Add image and API settings**

```bash
# .env.example
API_BASE_URL=http://localhost:8000
UNSPLASH_ACCESS_KEY=your-unsplash-access-key
PEXELS_API_KEY=your-pexels-api-key
IMAGE_PROVIDER=unsplash
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add image API settings to .env.example"
```

---

### Task 10: Run Full Test Suite & Lint

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: No errors

- [ ] **Step 3: Run type checker**

Run: `mypy src/agentic_tour_planner/api/ src/agentic_tour_planner/domain/`
Expected: No errors

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: lint and type check fixes for API streaming integration"
```
