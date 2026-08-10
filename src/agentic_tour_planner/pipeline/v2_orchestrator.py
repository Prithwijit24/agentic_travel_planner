"""New pipeline orchestrator (v2).

Wires retrieval -> sequencing -> critique loop -> narration -> validation
into a single entry point that produces a PlanningResponse matching v1 structure.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from agentic_tour_planner.agents.graph import run_critique_loop
from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.domain.models import (
    Citation,
    CostEstimate,
    CostLineItem,
    DailyCost,
    DayPlan,
    OverallCost,
    PlanningRequest,
    PlanningResponse,
    SpotDetail,
)
from agentic_tour_planner.narration.narrate import narrate_trip
from agentic_tour_planner.narration.validate import validate_narration
from agentic_tour_planner.retrieval.pipeline import retrieve, get_available_tags
from agentic_tour_planner.sequencing.bin_packer import sequence
from agentic_tour_planner.tools.weather import WeatherTool
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


async def generate_itinerary(
    request: PlanningRequest,
    emitter: Any = None,
) -> PlanningResponse:
    """Generate a full itinerary using the new pipeline."""
    destination = request.destination
    days = request.trip_length_days
    travelers = getattr(request, "travelers", 1)
    budget_level = request.budget_level
    interest_tags = getattr(request, "interest_tags", None) or []
    travel_month = getattr(request, "travel_month", None)

    _emit(emitter, "step", "Retrieve", "Retrieving POIs...")

    # 1. Retrieve POIs (or get balanced defaults if no interests)
    if not interest_tags:
        from agentic_tour_planner.retrieval.pipeline import get_balanced_default_pois
        poi_ids = get_balanced_default_pois(destination)
        if poi_ids:
            from agentic_tour_planner.retrieval.graph_retrieval import get_graph_db_or_none, enrich
            client = get_graph_db_or_none()
            if client:
                pois = enrich(poi_ids, client)
            else:
                pois = []
        else:
            pois = retrieve(destination, [])
    else:
        pois = retrieve(destination, interest_tags)
    if not pois:
        logger.warning("No POIs retrieved, returning empty response")
        return _empty_response(request)

    _emit(emitter, "debug", "Retrieve", "POIs retrieved", {"count": len(pois)})

    # 1b. Refresh stale POIs (only triggers LLM for stale ones)
    from agentic_tour_planner.agents.freshness_agent import refresh_pois
    pois = await refresh_pois(pois, destination)

    # 2. Filter out hotels (sleep POIs) from sequencing - they go to cost, not timeline
    hotels = [p for p in pois if p.get("category") == "sleep"]
    sight_pois = [p for p in pois if p.get("category") != "sleep"]
    logger.info(f"Sequencing: {len(sight_pois)} sight POIs, {len(hotels)} hotel POIs (filtered from timeline)")

    # 3. Sequence sight POIs into days
    _emit(emitter, "step", "Sequence", "Sequencing into days...")
    skeleton = sequence(sight_pois, duration_days=days)
    _emit(emitter, "debug", "Sequence", "Sequenced", {"days": len(skeleton)})

    # 4. Get weather
    weather = {}
    try:
        weather_tool = WeatherTool()
        snapshot = await weather_tool.current_weather(destination)
        if snapshot:
            weather = {"summary": snapshot.summary, "temperature_c": snapshot.temperature_c}
    except Exception as e:
        logger.warning("Weather fetch failed: {}".format(e))

    # 4. Run critique loop (cost -> budget critique -> timing critique -> revise)
    _emit(emitter, "step", "Critique", "Running critique loop...")
    state = TripState(
        trip_meta={
            "destination": destination,
            "travelers": travelers,
            "budget_level": budget_level,
            "duration_days": days,
            "daily_hour_budget": 8.0,
            "travel_month": travel_month,
        },
        retrieved_pois=pois,
        day_skeleton=skeleton,
        critiques=[],
        revision_count=0,
        weather=weather,
    )

    state = await run_critique_loop(state)
    cost_summary = state.get("cost_summary", {})
    known_limitations = state.get("known_limitations", [])
    skeleton = state.get("day_skeleton", skeleton)

    _emit(emitter, "debug", "Critique", "Critique loop done", {
        "revisions": state.get("revision_count", 0),
        "limitations": len(known_limitations),
    })

    # 5. Narrate
    _emit(emitter, "step", "Narrate", "Generating narration...")
    narration = await narrate_trip(
        trip_meta=state["trip_meta"],
        day_skeleton=skeleton,
        cost_summary=cost_summary,
        weather=weather,
        known_limitations=known_limitations,
    )

    # 6. Validate
    issues = validate_narration(narration, skeleton, cost_summary)
    if issues:
        logger.warning("Narration validation issues: {}".format(issues))

    _emit(emitter, "step", "Done", "Itinerary complete")

    # 7. Build response matching v1 structure
    return _build_response(request, narration, skeleton, cost_summary, weather, known_limitations)


def _build_response(
    request: PlanningRequest,
    narration: dict[str, Any],
    skeleton: list[dict[str, Any]],
    cost_summary: dict[str, Any],
    weather: dict[str, Any],
    known_limitations: list[str],
) -> PlanningResponse:
    """Build a PlanningResponse matching v1 structure."""
    narration_days = {d["day"]: d for d in narration.get("days", [])}

    # Build DayPlan for each day with proper structure
    itinerary = []
    for day in skeleton:
        day_num = day.get("day", 0)
        narration_day = narration_days.get(day_num, {})

        spots = []
        morning = []
        afternoon = []
        evening = []
        meals = []
        logistics = list(known_limitations)  # Start with known limitations

        for idx, poi in enumerate(day.get("pois", [])):
            # Build SpotDetail with full description from POI data
            spot = SpotDetail(
                name=poi.get("name", "Unknown"),
                lat=poi.get("lat"),
                lon=poi.get("long"),
                description=poi.get("long_description", ""),
                opening_hours=poi.get("hours"),
            )
            spots.append(spot)

            # Build timeline: distribute POIs across morning/afternoon/evening
            desc = poi.get("long_description", "")
            name = poi.get("name", "Unknown")
            hours = poi.get("hours", "")
            price = poi.get("price", "")

            # Create activity string with time window
            time_slot = _assign_time_slot(idx, len(day.get("pois", [])))
            activity = "{}: {}".format(time_slot, name)
            if hours:
                activity += " ({})".format(hours)
            if desc:
                # Use first sentence of description (up to 100 chars)
                first_sentence = desc.split(".")[0].strip()
                if len(first_sentence) > 100:
                    first_sentence = first_sentence[:97] + "..."
                activity += " - {}".format(first_sentence)

            if idx % 3 == 0:
                morning.append(activity)
            elif idx % 3 == 1:
                afternoon.append(activity)
            else:
                evening.append(activity)

            # Add meal suggestions for eat/drink categories
            category = poi.get("category", "")
            if category in ("eat", "drink"):
                meal_text = "Visit {} ({})".format(name, price if price else "budget-friendly")
                meals.append(meal_text)

        # Build theme from narration's title or generate from POIs
        theme = narration_day.get("title", "")
        if not theme:
            spot_names = [p.get("name", "?") for p in day.get("pois", [])]
            theme = "Explore {}".format(", ".join(spot_names[:3]))

        # Build summary from narration
        summary = narration_day.get("narrative", "")
        if not summary:
            summary = "Visit {} with {}.".format(
                ", ".join(p.get("name", "?") for p in day.get("pois", [])),
                day.get("city", "local area")
            )

        day_plan = DayPlan(
            day=day_num,
            theme=theme,
            summary=summary,
            morning=morning,
            afternoon=afternoon,
            evening=evening,
            meals=meals,
            logistics=logistics if logistics else ["Plan transport between spots"],
            spots=spots,
        )
        itinerary.append(day_plan)

    # Build cost estimate with named items
    cost_estimate = _build_cost_estimate(cost_summary, itinerary, request)

    # Build practical tips
    practical_tips = narration.get("general_tips", [])
    if known_limitations:
        # Prepend known limitations as tips
        practical_tips = known_limitations + practical_tips

    return PlanningResponse(
        overview=narration.get("overview", "Trip plan for {}".format(request.destination)),
        itinerary=itinerary,
        practical_tips=practical_tips,
        citations=[Citation(title="Wikivoyage", url="https://en.wikivoyage.org")],
        insights=_build_minimal_insights(request),
        provider_used="pipeline-v2",
        model_used="hybrid-graph-vector",
        monthly_weather="{}: {}".format(getattr(request, "travel_month", None) or "This month", weather.get("summary", "")),
        transport_options=[],
        cost_estimate=cost_estimate,
    )


def _build_cost_estimate(
    cost_summary: dict[str, Any],
    itinerary: list[DayPlan],
    request: PlanningRequest,
) -> CostEstimate | None:
    """Build CostEstimate with deterministic per-day breakdown."""
    if not cost_summary:
        return None

    travelers = getattr(request, "travelers", 1)
    budget_level = request.budget_level

    # Get cost agent's grand total as reference
    try:
        gt = cost_summary.get("grand_total", 0)
        if isinstance(gt, str):
            gt = gt.replace(",", "").replace("Rs", "").replace("INR", "").strip()
        agent_grand = float(gt)
    except (ValueError, TypeError):
        agent_grand = 0.0

    # Build per-day costs with deterministic estimates
    daily_costs = []
    for day in itinerary:
        items = []

        # Per-POI costs
        for spot in day.spots:
            name = spot.name or "Attraction"
            amount = 0.0
            # Check if POI description mentions a price
            if spot.description:
                desc_lower = spot.description.lower()
                if "free" in desc_lower:
                    amount = 0.0
                elif "rs" in desc_lower:
                    import re
                    match = re.search(r'rs\s*([\d,]+)', desc_lower)
                    if match:
                        amount = float(match.group(1).replace(",", ""))

            # Categorize by POI type
            category = ""
            for s in day.spots:
                if s.name == name:
                    # Check original POI category
                    break
            items.append(CostLineItem(label=name, amount=amount))

        # Fixed daily costs based on budget tier
        hotel_rates = {"budget": 1200, "midrange": 3500, "luxury": 12000}
        food_rates = {"budget": 400, "midrange": 1000, "luxury": 3000}
        transport_rates = {"budget": 200, "midrange": 500, "luxury": 1500}

        items.append(CostLineItem(label="Hotel (per night)", amount=float(hotel_rates.get(budget_level, 3500))))
        items.append(CostLineItem(label="Meals (per person)", amount=float(food_rates.get(budget_level, 1000) * travelers)))
        items.append(CostLineItem(label="Local transport", amount=float(transport_rates.get(budget_level, 500))))

        subtotal = sum(item.amount for item in items)
        daily_costs.append(DailyCost(day=day.day, items=items, subtotal=subtotal))

    # Calculate grand total from deterministic line items
    # (Cost agent's estimate is for the pre-revision skeleton, so we use our own breakdown)
    grand_total = sum(dc.subtotal or 0 for dc in daily_costs)

    return CostEstimate(
        daily=daily_costs,
        overall=OverallCost(
            grand_total=grand_total,
            per_person_total=grand_total / max(travelers, 1),
            members=travelers,
        ),
    )


def _assign_time_slot(index: int, total: int) -> str:
    """Assign a time window based on position in the day."""
    slots = [
        "Morning 8:00-10:00",
        "Late Morning 10:00-12:00",
        "Afternoon 14:00-16:00",
        "Late Afternoon 16:00-18:00",
        "Evening 19:00-21:00",
    ]
    if index < len(slots):
        return slots[index]
    return "Afternoon 14:00-16:00"


def _build_minimal_insights(request: PlanningRequest) -> Any:
    """Build minimal PlanningInsights for the response."""
    from agentic_tour_planner.domain.models import PlanningInsights, RouteGuidance, BudgetGuidance, TimingGuidance
    return PlanningInsights(
        route=RouteGuidance(strategy="Graph-based retrieval with deterministic sequencing"),
        budget=BudgetGuidance(estimated_daily_budget=0, estimated_total_budget=0, assumptions=["Cost estimated via cost agent"]),
        timing=TimingGuidance(season_summary="", booking_window="", day_planning_notes=[]),
    )


def _empty_response(request: PlanningRequest) -> PlanningResponse:
    """Return an empty response when no POIs found."""
    from agentic_tour_planner.domain.models import PlanningInsights, RouteGuidance, BudgetGuidance, TimingGuidance
    return PlanningResponse(
        overview="No POIs found for {}".format(request.destination),
        itinerary=[],
        practical_tips=[],
        citations=[],
        insights=PlanningInsights(
            route=RouteGuidance(strategy="None"),
            budget=BudgetGuidance(estimated_daily_budget=0, estimated_total_budget=0, assumptions=[]),
            timing=TimingGuidance(season_summary="", booking_window="", day_planning_notes=[]),
        ),
        provider_used="pipeline-v2",
        model_used="none",
    )


def _emit(emitter: Any, event: str, step: str, message: str, detail: dict | None = None) -> None:
    """Emit an event if emitter is available."""
    if emitter:
        from agentic_tour_planner.domain.models import LogEvent
        emitter.emit(LogEvent(event=event, step=step, message=message, detail=detail or {}))
