# Pipeline Latency Optimization Design

## Goal

Reduce end-to-end pipeline latency from ~800s to ~200s for interactive UI use, without dropping any features. User waits at UI currently and 800s is painful.

## Current Profile

| Stage | Time | % |
|---|---|---|
| Generate Plan | ~416s | 52% |
| Live Web Collection | ~127s | 16% |
| Cost Estimate | ~115s | 14% |
| Detailed Places: LLM Gen | ~112s | 14% |
| Rest (Gather, Parse, etc.) | ~30s | <4% |

Root cause analysis:

1. **Generate Plan (416s):** omniroute (`localhost:20128`, model `auto/best-fast`) handles the large itinerary generation prompt. Model is slow for this complex task.
2. **Cost Estimate (115s):** omniroute again, slow for multi-round tool-use LLM calls.
3. **Detailed Places (112s):** omniroute again.
4. **Live Web Collection (127s):** sequential I/O — search, YouTube metadata fetch, audio download, transcript, blog crawl, LLM extraction. Pure wall-clock from sequential network calls.
5. **Pipeline orchestration:** Gather Context → Build Insights → Live Web → Build Prompt → Generate Plan → post-processing — all sequential, no overlap.

## Changes

### 1. Per-role provider routing

Add two config keys to `llm.yml`:

```yaml
planner_provider: agnes
worker_provider: omniroute
```

- **Planner role** (Generate Plan, Detailed Places): routes to `agnes-2.0-flash` (cloud, ~20-30s per call). Falls back to omniroute if agnes fails.
- **Worker role** (route/budget/timing insights, cost estimator, live web extraction): stays on omniroute (fast for small JSON outputs).
- Falls back through the provider chain if the preferred role provider fails.

Files changed:
- `src/agentic_tour_planner/config/llm.yml` — add `planner_provider` and `worker_provider` keys
- `src/agentic_tour_planner/llm/provider.py` — read config; modify `complete_json` and `_chain_for` to inject role-preferred provider as first candidate; modify `complete_with_tools` and `extract_json` similarly

**Time impact:** Generate Plan 416s → ~25s. Cost Estimate 115s → ~10s. Detailed Places LLM 112s → ~10s. Total saved: ~600s.

### 2. Pipeline parallelism

Reorganize pipeline `run()` into concurrent phases:

```
Phase 1 (independent):     Gather Context  ──┐
                            Live Web Collection  ──┐   (concurrent)
                                                  │
Phase 2 (depends on ctx):  Build Insights ◄──────┘
                                                  │
Phase 3 (depends on all):  Build Prompt ◄────────┘
                            Generate Plan
                                                  │
Phase 4 (depends on plan): Build Citations ──┐
                            Parse Itinerary ──┤   (concurrent)
                            Transport Opts ──┤
                            Cost Estimate ───┘
```

Key points:
- Gather Context and Live Web Collection share no data — run concurrently.
- Build Insights needs gathered context — starts after Gather Context finishes.
- Cost Estimate runs concurrent with cheap post-processing steps (Citations, Parse, Transport).
- Live Web Collection's `place_hours` write to `context` happens before Build Prompt, avoiding race.

Files changed:
- `src/agentic_tour_planner/pipeline/agentic_pipeline.py` — restructure `run()` with `asyncio.create_task` / `asyncio.gather`

**Time impact:** Saves ~127s wall-clock (Live Web Collection unblocks from sequential chain). Saves ~115s from Cost running parallel to ~5s of other post-processing.

### 3. No dependencies added or removed

All existing features preserved:
- Live web data, cost estimates, detailed places, insights, weather, citations
- SSE streaming events
- Fallback plans on any LLM failure
- Provider override via CLI/UI still works

## Data Model

No model changes. `PlanningRequest` already has optional `provider` and `planner_model` fields that override the role routing when set explicitly.

## Risk

- **Race condition:** Live Web writes `context.place_hours` after its own completion. In parallel mode, Insights runs from the same `context` object. `place_hours` is only written to after Live Web completes — and Insights reads `context.weather`/`context.documents`, not `place_hours`. No race.
- **agnès availability:** If agnes is down, the planner falls through to omniroute in ~30s (timeout) → graceful degradation, same behavior as today.
- **Error propagation:** `asyncio.gather` with `return_exceptions=True` for post-processing so Cost failure doesn't block itinerary parsing.
