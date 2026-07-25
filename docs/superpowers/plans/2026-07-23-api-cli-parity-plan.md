# API-CLI Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the CLI's rich result dict (context, insights, response, detailed, profile) through the API's SSE `done` event instead of just the bare PlanningResponse.

**Architecture:** Three independent changes: (1) store context metadata on pipeline after gather_context, (2) assemble CLI-style dict in `_run_plan_job` and emit via SSE, (3) update UI to read from new key.

**Tech Stack:** FastAPI, Pydantic, SSE, Streamlit

## Global Constraints

- No new Pydantic models — use plain dicts for the full result
- Pipeline `profiler` attribute is already public — do not add another profiler accessor
- `detail["plan"]` key is removed from SSE done event; replaced by `detail["response"]`

---

### Task 1: Pipeline — expose context summary

**Files:**
- Modify: `src/agentic_tour_planner/pipeline/agentic_pipeline.py:43-56` (add `_context_summary` to `__init__`)
- Modify: `src/agentic_tour_planner/pipeline/agentic_pipeline.py:73` (store summary before return)
- Create: `tests/test_pipeline_context_summary.py`

**Interfaces:**
- Consumes: `AgenticTourPlannerPipeline.gather_context()` returns `RetrievedContext`
- Produces: `AgenticTourPlannerPipeline.context_summary` → `dict | None`

- [ ] **Step 1: Write the failing test**

```python
"""Test pipeline context_summary property."""
from __future__ import annotations

import pytest
from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline


@pytest.mark.asyncio
async def test_context_summary_populated_after_gather():
    pipeline = AgenticTourPlannerPipeline()
    assert pipeline.context_summary is None

    request = PlanningRequest(destination="Kyoto", interests=["temples"])
    ctx = await pipeline.gather_context(request)

    assert pipeline.context_summary is not None
    assert "documents_count" in pipeline.context_summary
    assert "search_results_count" in pipeline.context_summary
    assert "place_hours_count" in pipeline.context_summary
    assert "weather" in pipeline.context_summary
    assert pipeline.context_summary["documents_count"] >= 0
    assert pipeline.context_summary["search_results_count"] >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_context_summary.py -v --asyncio-mode=auto`
Expected: FAIL with `AttributeError: 'AgenticTourPlannerPipeline' object has no attribute '_context_summary'`

- [ ] **Step 3: Add `_context_summary` to `__init__`**

In `src/agentic_tour_planner/pipeline/agentic_pipeline.py`, after `self.profiler = StageTimer()`:

```python
self._context_summary: dict | None = None
```

And add a property after `__init__`:

```python
@property
def context_summary(self) -> dict | None:
    return self._context_summary
```

- [ ] **Step 4: Store summary at end of `gather_context`**

In `gather_context()`, right before the return on line 73:

```python
self._context_summary = {
    "documents_count": len(docs),
    "search_results_count": len(search_results),
    "place_hours_count": len(place_hours),
    "weather": weather.summary if weather else None,
}
return RetrievedContext(documents=docs, search_results=search_results, place_hours=place_hours, weather=weather)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_pipeline_context_summary.py -v --asyncio-mode=auto`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/pipeline/agentic_pipeline.py tests/test_pipeline_context_summary.py
git commit -m "feat: expose context_summary on pipeline after gather_context"
```

---

### Task 2: API — CLI compat wrapper in SSE done event

**Files:**
- Modify: `src/agentic_tour_planner/api/main.py:116-126`

**Interfaces:**
- Consumes: `pipeline.context_summary`, `pipeline.profiler.as_table()`, `response`, `detailed`
- Produces: SSE `done` event detail contains `request`, `context`, `insights`, `response`, `detailed`, `profile`

- [ ] **Step 1: Replace the SSE done event emission in `_run_plan_job`**

Current code (lines 116-127):
```python
emitter.emit(
    LogEvent(
        event="done",
        message="Plan complete",
        detail={
            "plan_id": response.plan_id,
            "request_id": request_id,
            "status": "completed",
            "plan": response.model_dump(mode="json"),
        },
    )
)
```

Replace with:
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
emitter.emit(
    LogEvent(event="done", message="Plan complete", detail=full_result)
)
```

- [ ] **Step 2: Verify the SSE event structure**

No automated test needed — the endpoint is async and requires a running server. Manual verification:

```bash
# Start the API
uv run tour-planner-api &

# POST a plan and stream SSE to see the done event
curl -N -X POST http://localhost:8000/plans \
  -H "Content-Type: application/json" \
  -d '{"destination":"Kyoto","trip_length_days":2,"interests":["temples"],"budget_level":"midrange","travel_month":"October","include_live_data":false}' \
  | grep "event: done" -A 100
```

Expected: The done event's `data` field contains `request`, `context`, `insights`, `response`, `detailed`, `profile`.

- [ ] **Step 3: Commit**

```bash
git add src/agentic_tour_planner/api/main.py
git commit -m "feat: emit CLI-style full result in SSE done event"
```

---

### Task 3: UI — extract plan from new SSE structure

**Files:**
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1201-1206`

**Interfaces:**
- Consumes: SSE `done` event detail with `response` key instead of `plan` key
- Produces: `stream_result["plan"]` populated from `detail["response"]`

- [ ] **Step 1: Update the `on_event` handler**

Current code (lines 1201-1206):
```python
elif event_type == "done":
    detail = event_data.get("detail") or {}
    if detail.get("status") == "error":
        stream_result["error"] = detail.get("error") or message
    if detail.get("plan"):
        stream_result["plan"] = detail["plan"]
```

Replace with:
```python
elif event_type == "done":
    detail = event_data.get("detail") or {}
    if detail.get("status") == "error":
        stream_result["error"] = detail.get("error") or message
    if detail.get("response"):
        stream_result["plan"] = detail["response"]
```

- [ ] **Step 2: Verify UI still renders plans**

Run the Streamlit UI:

```bash
uv run tour-planner-ui
```

Submit a plan request and verify the results page renders correctly with itinerary, spots, transport, cost, etc.

- [ ] **Step 3: Commit**

```bash
git add src/agentic_tour_planner/app/streamlit_app.py
git commit -m "fix(ui): read plan from SSE done event detail.response"
```
