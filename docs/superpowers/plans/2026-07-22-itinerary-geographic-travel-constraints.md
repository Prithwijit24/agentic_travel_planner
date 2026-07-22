# Itinerary Geographic Travel Constraints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add prompt-level geographic planning rules plus a Google Maps-backed post-generation validator that flags unrealistic day routes without breaking itinerary generation.

**Architecture:** `build_itinerary_prompt` remains the instruction source for the planner model. `DayPlan` gains a `rationale` field. A new focused `travel_constraints.py` module checks adjacent daily spots with Google Maps distance/time data after `enforce_minimum_daily_spots`, appending user-visible warnings to `logistics` and `rationale` only.

**Tech Stack:** Python 3.14, Pydantic models, FastAPI/Streamlit pipeline, `httpx.AsyncClient`, Google Maps Distance Matrix API, pytest.

## Global Constraints

- For `4-6` places per day, every day must return at least 4 visible places.
- Treat 4-6 as the recommended/core count; places above 6 are optional.
- No automatic reordering of places in this version.
- No hard failure when Google Maps is unavailable.
- No full clustering engine or global route optimizer.
- Warnings must be user-visible through existing day fields: `logistics` and `rationale`.
- Google Maps calls must be best-effort.

---

## File Structure

- Modify `src/agentic_tour_planner/domain/models.py`: add `DayPlan.rationale`.
- Modify `src/agentic_tour_planner/pipeline/prompts.py`: strengthen itinerary prompt and output contract.
- Create `src/agentic_tour_planner/pipeline/travel_constraints.py`: define travel warning data types, Google Distance Matrix lookup, and itinerary annotation.
- Modify `src/agentic_tour_planner/pipeline/agentic_pipeline.py`: call travel validator after minimum place enforcement.
- Modify `tests/unit/test_pipeline.py`: prompt/model regressions.
- Create `tests/unit/test_travel_constraints.py`: mocked validator tests.

---

### Task 1: Prompt and Day Model Contract

**Files:**
- Modify: `src/agentic_tour_planner/domain/models.py`
- Modify: `src/agentic_tour_planner/pipeline/prompts.py`
- Test: `tests/unit/test_pipeline.py`

**Interfaces:**
- Consumes: existing `DayPlan` Pydantic model and `build_itinerary_prompt(request, context, insights, live_web_brief=None) -> str`
- Produces: `DayPlan.rationale: str | None`; prompt text requiring geographic clustering, travel budget, long-jump warnings, multi-city sequence, and day rationale

- [ ] **Step 1: Write failing model test**

Add to `tests/unit/test_pipeline.py`:

```python
def test_day_plan_accepts_rationale():
    day = DayPlan(day=1, theme="North cluster", rationale="Covers nearby northern places and returns to base.")

    assert day.rationale == "Covers nearby northern places and returns to base."
```

- [ ] **Step 2: Write failing prompt regression test**

Add to `tests/unit/test_pipeline.py`:

```python
def test_prompt_requires_geographic_travel_constraints():
    request = PlanningRequest(destination="Sikkim", trip_length_days=4, places_per_day="4-6")
    context = RetrievedContext()
    insights = PlanningInsights(
        route=RouteGuidance(strategy="cluster by region"),
        budget=BudgetGuidance(estimated_daily_budget=100, estimated_total_budget=400),
        timing=TimingGuidance(season_summary="clear", booking_window="2 weeks"),
    )

    prompt = build_itinerary_prompt(request, context, insights)

    assert "GEOGRAPHIC CLUSTERING FIRST" in prompt
    assert "3-4 hours" in prompt
    assert "50-70 km" in prompt
    assert "1.5 hours" in prompt
    assert "Day N+1 must logically start" in prompt
    assert "multi-city" in prompt
    assert "rationale" in prompt
    assert "4-6 recommended/core places" in prompt
    assert "above 6" in prompt
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_pipeline.py::test_day_plan_accepts_rationale tests/unit/test_pipeline.py::test_prompt_requires_geographic_travel_constraints -q
```

Expected: `test_day_plan_accepts_rationale` fails because `DayPlan` has no `rationale`; prompt test fails because required phrases are missing.

- [ ] **Step 4: Add `DayPlan.rationale`**

Modify `src/agentic_tour_planner/domain/models.py`:

```python
class DayPlan(BaseModel):
    day: int
    theme: str
    summary: str | None = None
    rationale: str | None = None
    transport: str | None = None
    morning: list[str] = Field(default_factory=list)
    afternoon: list[str] = Field(default_factory=list)
    evening: list[str] = Field(default_factory=list)
    meals: list[str] = Field(default_factory=list)
    logistics: list[str] = Field(default_factory=list)
    weather: DayWeather | None = None
    spots: list[SpotDetail] = Field(default_factory=list)
    needs_hotel_change: bool = False
    hotel_recommendation: str | None = None
```

- [ ] **Step 5: Strengthen places-per-day prompt wording**

In `src/agentic_tour_planner/pipeline/prompts.py`, replace the ranged `places_rule` branch with wording shaped like:

```python
places_rule = (
    f"STRICT MINIMUM: Schedule AT LEAST {place_lo} notable places every day "
    f"(user requested '{request.places_per_day}'). Treat {place_lo}-{place_hi} as the "
    f"recommended/core places range for each day. Populate 'spots' with at least "
    f"{place_lo} distinct places; never fewer, even on the last day. Places above "
    f"{place_hi} must be clearly lower-priority optional extras. There are NO exceptions: "
    f"arrival, transfer, and departure days still need at least {place_lo} places."
    if place_lo != place_hi
    else f"STRICT MINIMUM: Schedule AT LEAST {place_lo} notable places every day "
    f"(user requested '{request.places_per_day}'). Never fewer. Populate 'spots' with the "
    f"same minimum. There are NO exceptions: arrival, transfer, and departure days still need at least {place_lo} places."
)
```

- [ ] **Step 6: Add geographic planning rules to prompt**

In the `STRICT PLANNING RULES` block in `build_itinerary_prompt`, add bullets before `COVERAGE`:

```text
- GEOGRAPHIC CLUSTERING FIRST: Before assigning places to days, group selected places into clusters by realistic road/transit proximity, not input order. Places in the same day should normally sit within a 1-2 hour travel radius.
- DAILY TRAVEL BUDGET: Keep each day's total local transit around 3-4 hours unless the user explicitly accepts a long-travel day. Do not add a place to a day when it pushes that day beyond this budget.
- LONG-JUMP WARNING: Do not silently place two same-day spots together when they are about 50-70 km apart or more than 1.5 hours apart. If unavoidable, write an explicit note such as "Note: Place X and Place Y are far apart; this day involves significant travel time."
- EFFICIENT ORDER: Within each day, sequence places to minimize backtracking. Start from one end of the cluster and move logically through nearby places.
- BASE CONTINUITY: If Day N ends far from the hotel/base, include the return-to-hotel leg in that day's logistics and travel budget. Day N+1 must logically start from the hotel/base or from the new hotel if needs_hotel_change=true.
- MULTI-CITY / MULTI-BASE: For multi-city or multi-region trips, choose the overall city sequence first to avoid backtracking, mark inter-city transit days, and do not stack a full sightseeing day on top of a long transfer. End with a one-line route summary.
- LOAD BALANCE AND HOURS: Balance sightseeing and travel load across days. Respect known opening hours and practical timing, such as sunset viewpoints late in the day.
- DAY RATIONALE: Each day object MUST include rationale: one sentence explaining the geographic cluster, travel budget, and base continuity. If distance/time is uncertain, say the estimate is approximate and recommend verifying in maps.
```

- [ ] **Step 7: Update output contract**

In the prompt output contract, change:

```text
day, theme, summary, transport, morning, afternoon, evening, meals, logistics, weather, spots,
needs_hotel_change, hotel_recommendation.
```

to:

```text
day, theme, summary, rationale, transport, morning, afternoon, evening, meals, logistics, weather, spots,
needs_hotel_change, hotel_recommendation.
```

- [ ] **Step 8: Run task tests**

Run:

```bash
uv run pytest tests/unit/test_pipeline.py::test_day_plan_accepts_rationale tests/unit/test_pipeline.py::test_prompt_requires_geographic_travel_constraints tests/unit/test_pipeline.py::test_enforces_requested_minimum_spots_per_regular_day -q
```

Expected: all listed tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/agentic_tour_planner/domain/models.py src/agentic_tour_planner/pipeline/prompts.py tests/unit/test_pipeline.py
git commit -m "feat: add geographic itinerary prompt contract"
```

---

### Task 2: Travel Constraint Validator

**Files:**
- Create: `src/agentic_tour_planner/pipeline/travel_constraints.py`
- Test: `tests/unit/test_travel_constraints.py`

**Interfaces:**
- Consumes: `PlanningRequest`, `DayPlan`, `SpotDetail`
- Produces: `async def annotate_travel_constraints(request: PlanningRequest, itinerary: list[DayPlan]) -> list[DayPlan]`
- Produces: `TravelLeg` dataclass with `origin`, `destination`, `distance_km`, `duration_minutes`

- [ ] **Step 1: Write failing long-leg test**

Create `tests/unit/test_travel_constraints.py`:

```python
import pytest

from agentic_tour_planner.domain.models import DayPlan, PlanningRequest, SpotDetail
from agentic_tour_planner.pipeline.travel_constraints import TravelLeg, annotate_travel_constraints


@pytest.mark.asyncio
async def test_annotates_long_adjacent_leg(monkeypatch):
    async def fake_lookup(origin: str, destination: str, request: PlanningRequest):
        return TravelLeg(origin=origin, destination=destination, distance_km=95.0, duration_minutes=130)

    monkeypatch.setattr("agentic_tour_planner.pipeline.travel_constraints.lookup_travel_leg", fake_lookup)
    request = PlanningRequest(destination="Sikkim", trip_length_days=1)
    itinerary = [
        DayPlan(
            day=1,
            theme="Spread out",
            spots=[SpotDetail(name="Gangtok"), SpotDetail(name="Pelling")],
        )
    ]

    result = await annotate_travel_constraints(request, itinerary)

    warning_text = " ".join(result[0].logistics)
    assert "far apart" in warning_text
    assert "95 km" in warning_text
    assert "130 min" in warning_text
    assert result[0].rationale is not None
    assert "significant travel time" in result[0].rationale
```

- [ ] **Step 2: Write failing daily-budget test**

Add to `tests/unit/test_travel_constraints.py`:

```python
@pytest.mark.asyncio
async def test_annotates_over_daily_travel_budget(monkeypatch):
    legs = {
        ("A", "B"): TravelLeg(origin="A", destination="B", distance_km=40.0, duration_minutes=100),
        ("B", "C"): TravelLeg(origin="B", destination="C", distance_km=45.0, duration_minutes=100),
        ("C", "D"): TravelLeg(origin="C", destination="D", distance_km=45.0, duration_minutes=80),
    }

    async def fake_lookup(origin: str, destination: str, request: PlanningRequest):
        return legs[(origin, destination)]

    monkeypatch.setattr("agentic_tour_planner.pipeline.travel_constraints.lookup_travel_leg", fake_lookup)
    request = PlanningRequest(destination="Testland", trip_length_days=1)
    itinerary = [
        DayPlan(
            day=1,
            theme="Heavy day",
            spots=[
                SpotDetail(name="A"),
                SpotDetail(name="B"),
                SpotDetail(name="C"),
                SpotDetail(name="D"),
            ],
        )
    ]

    result = await annotate_travel_constraints(request, itinerary)

    warning_text = " ".join(result[0].logistics)
    assert "daily travel budget" in warning_text
    assert "280 min" in warning_text
    assert "4 hours" in warning_text
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_travel_constraints.py -q
```

Expected: import failure because `travel_constraints.py` does not exist.

- [ ] **Step 4: Implement validator module**

Create `src/agentic_tour_planner/pipeline/travel_constraints.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import DayPlan, PlanningRequest
from agentic_tour_planner.tools.http_util import aretry_get
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

LONG_LEG_KM = 70.0
LONG_LEG_MINUTES = 90
DAILY_BUDGET_MINUTES = 240


@dataclass(frozen=True)
class TravelLeg:
    origin: str
    destination: str
    distance_km: float
    duration_minutes: int


async def annotate_travel_constraints(
    request: PlanningRequest,
    itinerary: list[DayPlan],
) -> list[DayPlan]:
    for day in itinerary:
        names = [spot.name.strip() for spot in day.spots if spot.name and spot.name.strip()]
        if len(names) < 2:
            continue
        total_minutes = 0
        for origin, destination in zip(names, names[1:]):
            leg = await lookup_travel_leg(origin, destination, request)
            if leg is None:
                continue
            total_minutes += leg.duration_minutes
            if leg.distance_km > LONG_LEG_KM or leg.duration_minutes > LONG_LEG_MINUTES:
                _append_warning(
                    day,
                    (
                        f"Note: {leg.origin} and {leg.destination} are far apart "
                        f"(~{leg.distance_km:.0f} km, ~{leg.duration_minutes} min); "
                        "this day involves significant travel time."
                    ),
                )
        if total_minutes > DAILY_BUDGET_MINUTES:
            _append_warning(
                day,
                (
                    f"Note: Day {day.day} exceeds the daily travel budget "
                    f"(~{total_minutes} min total transit, above 4 hours). "
                    "Verify this route in maps before finalizing."
                ),
            )
    return itinerary


async def lookup_travel_leg(
    origin: str,
    destination: str,
    request: PlanningRequest,
) -> TravelLeg | None:
    settings = get_settings()
    api_key = getattr(settings, "google_maps_api_key", None)
    if not api_key:
        logger.debug("Google Maps API key unavailable; skipping travel constraint lookup.")
        return None

    origin_query = quote_plus(f"{origin}, {request.destination}")
    destination_query = quote_plus(f"{destination}, {request.destination}")
    params = {
        "origins": origin_query,
        "destinations": destination_query,
        "key": api_key,
    }
    if request.transport_mode == "public":
        params["mode"] = "transit"
    elif request.transport_mode == "car":
        params["mode"] = "driving"

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await aretry_get(
                client,
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params=params,
            )
            response.raise_for_status()
        payload = response.json()
        rows = payload.get("rows") or []
        elements = rows[0].get("elements") if rows else []
        element = elements[0] if elements else {}
        if element.get("status") != "OK":
            logger.debug(f"Distance Matrix returned no route for {origin!r} to {destination!r}: {element.get('status')}")
            return None
        distance_m = float(element["distance"]["value"])
        duration_s = int(element["duration"]["value"])
        return TravelLeg(
            origin=origin,
            destination=destination,
            distance_km=distance_m / 1000,
            duration_minutes=round(duration_s / 60),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Travel constraint lookup failed for {origin!r} to {destination!r}: {exc}")
        return None


def _append_warning(day: DayPlan, warning: str) -> None:
    if warning not in day.logistics:
        day.logistics.append(warning)
    if day.rationale:
        if warning not in day.rationale:
            day.rationale = f"{day.rationale} {warning}"
    else:
        day.rationale = warning
```

- [ ] **Step 5: Run validator tests**

Run:

```bash
uv run pytest tests/unit/test_travel_constraints.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/pipeline/travel_constraints.py tests/unit/test_travel_constraints.py
git commit -m "feat: flag itinerary travel constraints"
```

---

### Task 3: Pipeline Integration

**Files:**
- Modify: `src/agentic_tour_planner/pipeline/agentic_pipeline.py`
- Test: `tests/unit/test_travel_constraints.py`

**Interfaces:**
- Consumes: `annotate_travel_constraints(request, itinerary) -> list[DayPlan]`
- Produces: pipeline output with minimum spots enforced first, then travel warnings annotated

- [ ] **Step 1: Write integration-order test**

Add to `tests/unit/test_travel_constraints.py`:

```python
@pytest.mark.asyncio
async def test_short_or_missing_route_data_does_not_add_warning(monkeypatch):
    async def fake_lookup(origin: str, destination: str, request: PlanningRequest):
        return None

    monkeypatch.setattr("agentic_tour_planner.pipeline.travel_constraints.lookup_travel_leg", fake_lookup)
    request = PlanningRequest(destination="Kyoto", trip_length_days=1)
    itinerary = [
        DayPlan(
            day=1,
            theme="Compact",
            rationale="Compact temple cluster.",
            spots=[SpotDetail(name="Kiyomizu-dera"), SpotDetail(name="Gion")],
        )
    ]

    result = await annotate_travel_constraints(request, itinerary)

    assert result[0].logistics == []
    assert result[0].rationale == "Compact temple cluster."
```

- [ ] **Step 2: Run new test**

Run:

```bash
uv run pytest tests/unit/test_travel_constraints.py::test_short_or_missing_route_data_does_not_add_warning -q
```

Expected: pass once Task 2 exists.

- [ ] **Step 3: Import validator in pipeline**

Modify imports in `src/agentic_tour_planner/pipeline/agentic_pipeline.py`:

```python
from agentic_tour_planner.pipeline.place_constraints import enforce_minimum_daily_spots
from agentic_tour_planner.pipeline.travel_constraints import annotate_travel_constraints
```

- [ ] **Step 4: Call validator after place-count enforcement**

Replace:

```python
itinerary = enforce_minimum_daily_spots(request, itinerary)
logger.debug(f"Parsed {len(itinerary)} itinerary days.")
```

with:

```python
itinerary = enforce_minimum_daily_spots(request, itinerary)
itinerary = await annotate_travel_constraints(request, itinerary)
logger.debug(f"Parsed {len(itinerary)} itinerary days.")
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_pipeline.py tests/unit/test_travel_constraints.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/pipeline/agentic_pipeline.py tests/unit/test_travel_constraints.py
git commit -m "feat: annotate pipeline travel warnings"
```

---

### Task 4: Final Verification

**Files:**
- Read/verify only unless failures point to a missed task file

**Interfaces:**
- Consumes: all previous tasks
- Produces: verified feature

- [ ] **Step 1: Compile changed package**

Run:

```bash
uv run python -m py_compile \
  src/agentic_tour_planner/domain/models.py \
  src/agentic_tour_planner/pipeline/prompts.py \
  src/agentic_tour_planner/pipeline/place_constraints.py \
  src/agentic_tour_planner/pipeline/travel_constraints.py \
  src/agentic_tour_planner/pipeline/agentic_pipeline.py
```

Expected: no output and exit code 0.

- [ ] **Step 2: Run targeted tests**

Run:

```bash
uv run pytest tests/unit/test_pipeline.py tests/unit/test_travel_constraints.py tests/unit/test_models.py tests/integration/test_api.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git diff --stat
git diff -- src/agentic_tour_planner/domain/models.py src/agentic_tour_planner/pipeline/prompts.py src/agentic_tour_planner/pipeline/travel_constraints.py src/agentic_tour_planner/pipeline/agentic_pipeline.py tests/unit/test_pipeline.py tests/unit/test_travel_constraints.py
```

Expected: diff only covers prompt contract, `rationale`, travel validator, pipeline integration, and tests.

- [ ] **Step 4: Commit verification fixes if needed**

If Step 1 or Step 2 required fixes, commit them:

```bash
git add src/agentic_tour_planner/domain/models.py src/agentic_tour_planner/pipeline/prompts.py src/agentic_tour_planner/pipeline/travel_constraints.py src/agentic_tour_planner/pipeline/agentic_pipeline.py tests/unit/test_pipeline.py tests/unit/test_travel_constraints.py
git commit -m "test: verify itinerary travel constraints"
```

Expected: only needed when verification found an issue.
