# API Streaming & UI Integration Design

## Goal

Connect the Streamlit UI to the FastAPI backend with validated Pydantic models, add a streaming log endpoint (SSE) for live progress feedback, and a separate image endpoint for place photos.

## Architecture: Dual-Endpoint (Approach A)

Two FastAPI endpoints serve the UI:

1. **`POST /plans`** — synchronous, returns validated `PlanAPIResponse` (wrapped `PlanningResponse` + `request_id`)
2. **`GET /plans/stream/{request_id}`** — SSE stream of `LogEvent` Pydantic models showing pipeline progress
3. **`GET /plans/{plan_id}/images`** — resolves LLM-generated image queries to Unsplash/Pexels URLs

## Pydantic Models

### Streaming Log Event

```python
class LogEvent(BaseModel):
    """A single event in the SSE stream."""
    event: Literal["step", "debug", "metric", "error", "done"]
    step: str | None = None          # e.g. "Gather Context"
    message: str                     # human-readable log line
    detail: dict[str, Any] | None = None  # debug payloads (doc counts, timing, etc.)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

### API Response Wrapper

```python
class PlanAPIResponse(BaseModel):
    """Validated response the UI maps from — ensures no null/missing fields."""
    request_id: str               # generated as str(uuid4()) per request
    plan: PlanningResponse
    status: Literal["completed", "error"]
    error: str | None = None
```

### Image Models

The `image_query` field is added to the existing place model within `PlanningResponse`:

```python
# Added to DayPlan.spots (or equivalent place model)
class PlaceVisit(BaseModel):
    # ... existing fields ...
    image_query: str | None = None   # LLM-generated search term for images
```

```python
class PlaceImage(BaseModel):
    place_name: str
    image_query: str          # LLM-generated search term
    image_url: str | None     # resolved URL from Unsplash/Pexels
    source: str | None        # "unsplash" | "pexels"

class ImageResponse(BaseModel):
    plan_id: str
    images: list[PlaceImage]
```

## API Endpoints

### Existing (unchanged)

- `GET /health`
- `GET /plans` — list stored plans
- `POST /feedback`
- `GET /metrics`

### Modified

- **`POST /plans`** — now returns `PlanAPIResponse` instead of raw `PlanningResponse`. **Breaking change**: response wraps `PlanningResponse` inside `PlanAPIResponse` with added `request_id`, `status`, and `error` fields. The `request_id` is generated as `str(uuid4())` per request. Internally runs the pipeline, saves to store, returns the validated response.

### New

- **`GET /plans/stream/{request_id}`** — SSE endpoint (`text/event-stream`). Each event is a JSON-encoded `LogEvent`. Uses `asyncio.Queue` to bridge pipeline logging to async SSE. Events: `step`, `debug`, `metric`, `error`, `done`.

- **`GET /plans/{plan_id}/images`** — Returns `ImageResponse` with resolved image URLs. Queries Unsplash/Pexels API using `image_query` fields from each place in the plan.

## Streaming Implementation

### EventEmitter

```python
class EventEmitter:
    """Collects log events during pipeline execution."""
    def __init__(self):
        self._queue: asyncio.Queue[LogEvent] = asyncio.Queue()
    
    def emit(self, event: LogEvent):
        self._queue.put_nowait(event)
    
    async def stream(self):
        while True:
            event = await self._queue.get()
            yield event
            if event.event == "done":
                break
```

### SSE Endpoint Wiring

```python
@app.get("/plans/stream/{request_id}")
async def stream_plan(request_id: str):
    emitter = get_emitter(request_id)  # lookup from in-memory registry
    return EventSourceResponse(emitter.stream())
```

The pipeline run registers an `EventEmitter` by `request_id` before starting, emits `LogEvent` objects at each step, and cleans up after `done`. The SSE endpoint looks up the emitter and streams it.

### Log Events Per Pipeline Step

| Step | Event | Message |
|------|-------|---------|
| 1 | `step` | "Gathering context..." |
| 1 | `debug` | `{documents_count, search_results_count, place_hours_count}` |
| 2 | `step` | "Building insights..." |
| 2 | `debug` | `{route_strategy_preview, budget_estimate}` |
| 3 | `step` | "Generating plan..." |
| 3 | `metric` | `{provider, model, latency_s, tokens}` |
| 4 | `step` | "Fetching images..." |
| done | `done` | `{plan_id, status}` |

## Streamlit UI Integration

### Data Flow

1. User fills form → clicks "Generate Plan"
2. UI calls `POST {API_BASE_URL}/plans` with `PlanningRequest` → gets `PlanAPIResponse` (with `request_id`)
3. UI opens SSE connection to `GET {API_BASE_URL}/plans/stream/{request_id}`
4. Loading animation displays live `LogEvent` messages in terminal + progress indicator
5. On `done` event, UI calls `GET {API_BASE_URL}/plans/{plan_id}/images` for images
6. UI renders the full plan with images

### API Base URL

Read from `API_BASE_URL` environment variable (e.g., `http://localhost:8000` in dev, `https://api.travelplanner.com` in prod).

### Loading Animation

- Replace hardcoded mock logs with real SSE `LogEvent` messages
- Add progress bar that advances per `step` event (4 steps = 25% each)
- Terminal shows the `message` field from each `LogEvent`
- On `done`, transition to results page with real data

### UI Field Mapping

| PlanningResponse Field | UI Section |
|----------------------|------------|
| `overview` | Trip Overview |
| `itinerary` | Day tabs |
| `cost_estimate` | Budget section |
| `transport_options` | Transport section |
| `citations` | Sources section |
| `practical_tips` | Tips section |
| `ImageResponse.images` | Place images in each day's spots |

## Error Handling

### Pipeline Errors

- If the pipeline raises an exception, the SSE stream emits an `error` event with the message, then `done` with `status: "error"`
- The `PlanAPIResponse` includes `error: str | None` field for the UI to display

### SSE Disconnection

- If the client disconnects mid-stream, the server-side emitter is cleaned up after a timeout (30s)
- The pipeline continues running (it doesn't abort) — the result is stored normally

### Image Endpoint Failures

- If Unsplash/Pexels API is down or rate-limited, `image_url` is `null` in the response
- UI gracefully degrades: shows a placeholder image or skips the image

### CORS

- Already configured with `allow_origins=["*"]` — no changes needed for cross-origin SSE

### Timeout

- `POST /plans` has no hard timeout (pipeline can take 30-60s). The SSE stream keeps the connection alive so the client knows progress is happening.

## Dependencies

- `sse-starlette` — SSE support for FastAPI
- `httpx` — async HTTP client for Unsplash/Pexels API calls
- Unsplash/Pexels API keys (configured via environment variables)

## Scope

- Modifies: `api/main.py`, `pipeline/agentic_pipeline.py`, `domain/models.py`, `app/streamlit_app.py`
- New files: `api/events.py` (EventEmitter), `api/images.py` (image endpoint)
- Does NOT modify: CLI, ingestion, evaluation, retrieval modules
