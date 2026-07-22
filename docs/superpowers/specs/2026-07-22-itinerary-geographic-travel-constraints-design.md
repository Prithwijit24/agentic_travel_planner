# Itinerary Geographic Travel Constraints Design

## Goal

Make itinerary generation respect geographic clustering, realistic daily travel limits, and explicit long-travel warnings while preserving the existing places-per-day guarantee.

For a request such as `4-6` places per day, each day must still return at least 4 visible places. The planner should treat 4-6 as the recommended/core range, and any places beyond 6 should be marked optional.

## Current Context

The main itinerary prompt is built in `src/agentic_tour_planner/pipeline/prompts.py` by `build_itinerary_prompt`.

The domain day object is `DayPlan` in `src/agentic_tour_planner/domain/models.py`.

Existing place-count enforcement lives in `src/agentic_tour_planner/pipeline/place_constraints.py` as `enforce_minimum_daily_spots`. It post-processes `DayPlan.spots` so the requested lower bound is not missed.

Google Maps support exists today for geocoding and map rendering in `src/agentic_tour_planner/tools/map_tool.py`, using `google_maps_api_key` from settings. There is no existing distance/time validator for itinerary legs.

## Proposed Approach

Use a prompt-plus-validator approach.

The prompt tells the planner how to build the itinerary:

- Cluster places geographically before assigning days.
- Respect a daily travel-time budget of about 3-4 hours unless the user accepts long travel.
- Avoid putting places in the same day when they are more than about 50-70 km apart or more than about 1.5 hours apart.
- If such pairing is unavoidable, explicitly warn the user.
- Order places within each day efficiently.
- Account for return-to-hotel and next-day start continuity.
- For multi-city or multi-base trips, choose the city sequence first, mark travel days, and avoid stacking full sightseeing on long travel days.
- Balance daily sightseeing and travel load.
- Respect known opening hours and practical timing constraints.
- Include a one-line rationale per day explaining the grouping.
- Mark uncertain distance/time estimates as approximate and recommend verification with maps.

The validator checks the generated day plans after the model returns. It flags issues but does not reorder, remove, or rewrite places in this first version.

## Data Model

Add `rationale: str | None = None` to `DayPlan`.

The rationale should explain the day's clustering and continuity, for example:

`Day 2 covers the northern cluster within about 20 km, then returns to the hotel in the evening.`

## Travel Validator

Add a focused module at `src/agentic_tour_planner/pipeline/travel_constraints.py`.

Inputs:

- `PlanningRequest`
- `list[DayPlan]`
- Google Maps API key through settings

Behavior:

- Read each day's ordered `spots`.
- Query Google Maps Distance Matrix or Directions API for adjacent spot pairs when the API key is available.
- Compute per-leg distance and duration.
- Compute total local transit duration for the day.
- If adjacent spots are more than 70 km apart or more than 90 minutes apart, append an explicit warning to `day.logistics` and `day.rationale`.
- If total local transit exceeds 4 hours, append an explicit warning to `day.logistics` and `day.rationale`.
- If Google Maps is unavailable or a lookup fails, do not invent exact values. Add approximate/verification wording only where the plan is making a distance-sensitive claim.

This version should not reorder spots because reordering can desync activity text, meals, opening-hour assumptions, and UI rendering.

## Places-Per-Day Contract

Keep `enforce_minimum_daily_spots` as the source of the lower-bound guarantee.

Prompt wording should clarify:

- For `4-6`, return at least 4 spots every day.
- Treat 4-6 as the recommended/core count.
- Spots beyond 6 can be included only as optional.
- Arrival, transfer, and departure days still need the lower bound unless future product requirements explicitly change that behavior.

## Error Handling

Google Maps calls must be best-effort. Failures should not fail the entire itinerary.

If the API key is missing, the planner still uses prompt-level geographic rules and existing route guidance.

If Google Maps returns no route for a pair, skip exact warning for that leg unless other available data clearly indicates a long jump.

Warnings must be user-visible through existing day fields: `logistics` and `rationale`.

## Tests

Add or update tests for:

- `build_itinerary_prompt` contains geographic clustering, travel-budget, long-jump warning, multi-city sequence, and rationale requirements.
- `DayPlan` accepts `rationale`.
- mocked travel validator flags a long adjacent leg.
- mocked travel validator flags a day whose total travel time exceeds 4 hours.
- existing minimum-spots tests still pass, including `4-6` producing at least 4 spots.

## Non-Goals

No automatic reordering of places in this version.

No hard failure when Google Maps is unavailable.

No full clustering engine or global route optimizer yet.

No UI redesign. The UI can render `rationale` later if needed; this change only ensures the field exists and is available.
