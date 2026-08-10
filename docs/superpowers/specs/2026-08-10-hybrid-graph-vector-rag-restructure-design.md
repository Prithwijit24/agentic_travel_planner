# Hybrid Graph/Vector RAG Restructure — Design Spec

**Date:** 2026-08-10
**Status:** Approved
**Author:** Prithwijit

## Overview

Restructure the agentic-travel-planner from an LLM-heavy multi-pass pipeline (~745s) into a hybrid graph/vector RAG system with deterministic retrieval/sequencing and a real multi-agent critique loop. Target: <60s itinerary generation, no hallucinated POIs, modular architecture, knowledge-graph-backed data.

## Architecture

### New packages

```
src/agentic_tour_planner/
  graphdb/           # Neo4j ingestion + client (Phase 0-1)
  vectordb/          # Chroma client + embedding (Phase 2)
  retrieval/         # Unified retrieval with fallback (Phase 3, 3B, 7, 8)
  sequencing/        # Deterministic bin-packing (Phase 4)
  agents/            # Cost agent + LangGraph critique loop (Phase 5-6)
  narration/         # Single-pass LLM narration + validation (Phase 9-10)
  pipeline/          # REWIRED: orchestrates all of the above (Phase 11)
```

### Data flow

```
User request (destination, interests, days, budget_tier, travelers)
    → retrieval.pipeline.retrieve()          [graph candidates → vector filter → enrich]
    → sequencing.bin_packer.sequence()       [deterministic day assignment]
    → agents.graph (LangGraph critique loop)  [cost → budget critique → timing critique → revise]
    → narration.narrate.narrate_trip()        [single LLM pass]
    → narration.validate.validate_narration() [hallucination + cost checks]
    → PlanningResponse (same shape as today)
```

### Fallback behavior

Each retrieval step checks backend availability. If Neo4j is down, `get_candidates()` falls back to AI Infra Stack API search. If Chroma is down, `filter_by_interest()` falls back to API-based relevance scoring. Fallback is transparent to downstream consumers.

## Design Decisions

### 1. Retrieval layer — Strategy pattern with per-step fallback

**Protocol interface:**
```python
# retrieval/protocol.py
class CandidateSource(Protocol):
    def get_candidates(self, destination: str) -> list[str]: ...

class InterestFilter(Protocol):
    def filter_by_interest(self, poi_ids: list[str], interest_tags: list[str], top_k: int = 40) -> list[str]: ...

class Enricher(Protocol):
    def enrich(self, poi_ids: list[str]) -> list[dict]: ...
```

**Three implementations per protocol:**
- `graph_retrieval.py` — Neo4j Cypher queries (primary)
- `vector_retrieval.py` — Chroma similarity search (primary)
- `api_retrieval.py` — AI Infra Stack API (fallback)

**Pipeline orchestration:**
```python
# retrieval/pipeline.py
def retrieve(destination: str, interest_tags: list[str]) -> list[dict]:
    poi_ids = _try_primary_else_fallback(graph_get_candidates, api_get_candidates, destination)
    filtered = _try_primary_else_fallback(vector_filter_by_interest, api_filter_by_interest, poi_ids, interest_tags)
    return enrich(filtered)
```

### 2. Sequencing — Deterministic bin-packing

**`sequencing/bin_packer.py`:**
- `sequence(pois, duration_days, daily_hour_budget=8.0) -> list[dict]`
- Groups POIs by `base_city`, orders groups by largest cluster first, greedily packs into days by `avg_visit_hrs` budget.
- Deterministic: same input → same output. Missing `avg_visit_hrs` defaults to 1.5.
- Output: `[{"day": 1, "city": "Gangtok", "pois": [...]}, ...]`

### 3. Cost agent — LLM classification + arithmetic

**`agents/cost_agent.py`:**
```python
def estimate_cost(state: TripState) -> TripState:
    # One LLM call classifies each cost line as:
    #   - per_person (entries, meals, tickets) → multiply by travelers
    #   - per_room (hotels) → multiply by rooms needed (travelers/occupancy)
    #   - flat (cab, vehicle hire, guide) → count once per use
    # Returns structured cost with per-line itemization + grand total
```

The LLM provides *reasoning* about cost type; actual prices come from POI data or small lookup tables.

### 4. LangGraph critique loop — TypedDict state, bounded iterations

**`agents/state.py`:**
```python
class TripState(TypedDict):
    trip_meta: dict
    retrieved_pois: list[dict]
    day_skeleton: list[dict]
    cost_summary: dict
    weather: dict
    critiques: list[str]
    revision_count: int
    known_limitations: list[str]
```

**`agents/graph.py`:**
```
cost_agent → budget_agent → timing_agent → should_revise?
    ├─ yes (critiques AND revision_count < 2) → planner_agent → cost_agent
    └─ no → END
```

- **cost_agent:** LLM classifies costs, produces itemized breakdown
- **budget_agent:** Arithmetic check against per-person/day threshold for budget_tier
- **timing_agent:** Checks `sum(avg_visit_hrs) + estimated_travel_time` against `daily_hour_budget`
- **planner_agent:** One LLM call → structured revision instruction → applied in code
- **Hard cap:** `revision_count < 2`. Surviving critiques become `known_limitations`.

### 5. Narration — Single LLM pass + validation

**`narration/narrate.py`:**
```python
def narrate_trip(trip_meta, day_skeleton, cost_summary, weather, known_limitations) -> dict:
    # ONE LLM call with fixed skeleton + cost + weather + limitations
    # Explicit instructions: "do not reorder, do not invent POIs, do not hallucinate facts"
    # Returns: {"overview": str, "days": [{"day": int, "narrative": str, "tip": str}], "general_tips": [str]}
    # Retry once on JSON parse failure, then fall back to template.
```

**`narration/validate.py`:**
```python
def validate_narration(narration, day_skeleton, cost_summary) -> list[str]:
    # Non-LLM checks:
    #   - cost mentioned in narration ≈ cost_summary["grand_total"]
    #   - every POI name in narration exists in day_skeleton
    #   - no POI from skeleton is missing from its day's narrative
    # Returns issues list. Non-empty → regenerate only affected day.
```

### 6. Cutover — Direct replacement, no feature flag

The existing pipeline is replaced directly. API/CLI/UI surfaces are rewired in one go. No feature flag, no dual maintenance. Old pipeline code is deleted.

## Phase Plan

| Phase | Description | Key deliverable |
|-------|-------------|-----------------|
| 0 | Environment setup (Neo4j, ChromaDB, deps) | Running infra, importable deps |
| 1 | Wikivoyage → Neo4j ingestion | `:Place` and `:POI` nodes with edges |
| 2 | Chroma vector store from POIs | `poi_descriptions` collection |
| 3 | Deterministic retrieval layer | `retrieve()` function working standalone |
| 3B | Dynamic interest tags | Per-destination tags replace static UI list |
| 4 | Deterministic sequencing | `sequence()` deterministic + budget-aware |
| 5 | Cost agent | LLM-classified cost breakdown |
| 6 | LangGraph critique loop | Bounded 2-iteration loop, terminates |
| 7 | RAG query reformulation | Reformulated retrieval behind feature flag |
| 8 | Freshness agent | Stale POI backfill + persist |
| 9 | Single-pass narration | One LLM call replaces 3-pass generation |
| 10 | Validation pass | Non-LLM checks + targeted regeneration |
| 11 | Rewire API/CLI/UI | All surfaces work end-to-end |
| 12 | Final validation & profiling | <60s target, before/after profiles |

## Testing strategy

- Existing tests on unchanged modules (llm, api events, image pipeline, CLI renderer) stay green.
- As each phase replaces a module, its tests get rewritten to match the new architecture.
- Old tests for replaced code are deleted.
- New modules get one test per public function (minimum).
- Integration test: `scripts/test_v2_e2e.py` runs a full itinerary for Sikkim, asserts shape + no hallucinations + timing < 60s.

## Success criteria

1. **Speed:** Itinerary generated in <60s (down from ~745s)
2. **Quality:** No hallucinated POIs, correct cost math, coherent narrative
3. **Modularity:** Retrieval, sequencing, agents, narration are independently testable/replaceable
4. **Data-backing:** Real POI data from Wikivoyage powers the itinerary

## Out of scope

- Changing the API/CLI/UI output shape
- Replacing the image pipeline
- Replacing the LLM provider
- Building new frontend features
- Transit data (bus/train schedules) — geographic proximity only for now
