# API-CLI Parity: Expose CLI-Style Full Result via API

**Date:** 2026-07-23
**Status:** Draft → Approved
**Author:** Prithwijit / agent

## Problem

The CLI (`tour-planner-plan`) returns a rich result dict from its
`run_pipeline()` function with separate top-level keys:

- `request` — echoed input
- `context` — metadata about retrieved documents, search results, place hours, weather
- `insights` — route/budget/timing guidance
- `response` — the full `PlanningResponse` (itinerary, spots, transport, costs, etc.)
- `detailed` — rich guidebook-style place-by-place data (`DetailedPlan`)
- `profile` — pipeline stage timing rows

The API's `POST /plans` endpoint delivers the plan through the SSE `done`
event's `detail.plan` field — but this only contains the bare `PlanningResponse`,
without the separate `context`, `insights`, `detailed`, or `profile` sections the
CLI provides.

## Solution

Keep `POST /plans` asynchronously returning `{request_id, status: "pending"}`.
Enrich the SSE `done` event to carry the full CLI-style payload, so consumers
(UI, external clients) get the same rich data the CLI returns.

## Changes

### 1. Pipeline — expose context summary

**File:** `src/agentic_tour_planner/pipeline/agentic_pipeline.py`

Add a `_context_summary` attribute to `AgenticTourPlannerPipeline`, populated
at the end of `gather_context()`, and exposed as a `context_summary` property.

```python
# In __init__:
self._context_summary: dict | None = None

# Property:
@property
def context_summary(self) -> dict | None:
    return self._context_summary

# In gather_context(), after creating ctx:
self._context_summary = {
    "documents_count": len(ctx.documents),
    "search_results_count": len(ctx.search_results),
    "place_hours_count": len(ctx.place_hours),
    "weather": ctx.weather.summary if ctx.weather else None,
}
```

No other pipeline changes. The `profiler` attribute is already public.

### 2. API — CLI compat wrapper

**File:** `src/agentic_tour_planner/api/main.py`

Replace the current SSE `done` event emission in `_run_plan_job()` to assemble
and emit a full CLI-style payload:

```python
full_result = {
    "plan_id": response.plan_id,
    "request_id": request_id,
    "status": "completed",
    "request": request.model_dump(mode="json"),
    "context": pipeline.context_summary,
    "insights": response.insights.model_dump(mode="json") if response.insights else None,
    "response": response.model_dump(mode="json"),
    "detailed": detailed.model_dump(mode="json") if detailed else None,
    "profile": pipeline.profiler.as_table(),
}

emitter.emit(LogEvent(event="done", message="Plan complete", detail=full_result))
```

On failure the `done` event remains `{request_id, status: "error", error: str}`.

### 3. UI — extract plan from new SSE structure

**File:** `src/agentic_tour_planner/app/streamlit_app.py`

Change the `on_event` handler in `_start_generation_job()` to read the plan from
`detail["response"]` instead of `detail["plan"]`:

```python
elif event_type == "done":
    detail = event_data.get("detail") or {}
    if detail.get("status") == "error":
        stream_result["error"] = detail.get("error") or message
    if detail.get("response"):
        stream_result["plan"] = detail["response"]
```

The `PlanAPIResponse` model has a `plan: PlanningResponse | None` field. It
will no longer be populated by the done event (the `response` key carries the
same data). The model is unchanged — the field just remains `null` in the
initial POST response as before.

### 4. Endpoints NOT changed

- `GET /plans` — stays as-is
- `GET /plans/{plan_id}/images` — stays as-is
- `POST /feedback` — stays as-is
- `GET /sources` — stays as-is
- `GET /plans/stream/{request_id}` — stays as-is (still delivers SSE events)
- `GET /health` — stays as-is
- `GET /metrics` — stays as-is

## Error Handling

If the pipeline fails:
- SSE emits a `done` event with `{request_id, status: "error", error: str}`
- No CLI-style payload is emitted
- Error logged, latency recorded, existing counters incremented

## Data Flow

```
Client                     API Server                    Pipeline
  │                          │                              │
  │  POST /plans             │                              │
  │ ──────────────────────►  │                              │
  │  {request_id, pending}   │                              │
  │ ◄────────────────────────│                              │
  │                          │  pipeline.run(request)       │
  │                          │ ──────────────────────────►  │
  │                          │  SSE: step/debug/metric      │
  │  ◄── SSE stream ────────│◄───────────────────────────  │
  │                          │  pipeline returns response   │
  │                          │ ◄──────────────────────────  │
  │                          │  pipeline.run_detailed()     │
  │                          │ ──────────────────────────►  │
  │                          │  detailed plan returned      │
  │                          │ ◄──────────────────────────  │
  │                          │  assemble full_result dict   │
  │                          │  SSE: done + full_result     │
  │  ◄── SSE: done ─────────│                              │
  │  with full payload       │                              │
```

## Testing

1. **Unit:** Test `pipeline.context_summary` returns correct metadata after
   `pipeline.run()` completes.
2. **Integration:** Send `POST /plans`, connect to SSE stream, verify `done`
   event contains `request`, `context`, `insights`, `response`, `detailed`, `profile`.
3. **UI:** Verify the plan renders correctly with data from `detail["response"]`.

## Open Questions / Future

- The SSE `PlanAPIResponse.plan` field becomes unused payload in the POST
  response. Could be removed in a future cleanup.
- No model changes needed — this is purely an assembly change.
