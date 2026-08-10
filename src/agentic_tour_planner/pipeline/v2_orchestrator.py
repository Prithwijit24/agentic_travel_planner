"""New pipeline orchestrator (v2).

Wires retrieval -> sequencing -> critique loop -> narration -> validation
into a single entry point that produces a PlanningResponse.
"""

from __future__ import annotations

import asyncio
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
    DayWeather,
    OverallCost,
    PlanningRequest,
    PlanningResponse,
    SpotDetail,
    TransportOption,
)
from agentic_tour_planner.narration.narrate import narrate_trip
from agentic_tour_planner.narration.validate import validate_narration
from agentic_tour_planner.retrieval.pipeline import retrieve, get_available_tags, get_balanced_default_pois
from agentic_tour_planner.sequencing.bin_packer import sequence
from agentic_tour_planner.tools.weather import WeatherTool
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


async def generate_itinerary(
    request: PlanningRequest,
    emitter: Any = None,
) -> PlanningResponse:
    """Generate a full itinerary using the new pipeline.

    Args:
        request: The planning request.
        emitter: Optional event emitter for SSE progress.

    Returns:
        PlanningResponse with the same shape as the old pipeline.
    """
    destination = request.destination
    days = request.trip_length_days
    travelers = getattr(request, "travelers", 1)
    budget_tier = getattr(request, "budget_tier", "midrange")
    interest_tags = getattr(request, "interest_tags", None) or []

    _emit(emitter, "step", "Retrieve", "Retrieving POIs...")

    # 1. Retrieve POIs (or get balanced defaults if no interests)
    if not interest_tags:
        # No interests specified - get balanced defaults
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
        # Try RAG reformulation if enabled
        from agentic_tour_planner.agents.retrieval_agent import reformulate_and_retrieve
        pois = await reformulate_and_retrieve(
            destination, interest_tags,
            retrieve_fn=lambda dest, tags: retrieve(dest, tags),
        )
    if not pois:
        logger.warning("No POIs retrieved, returning empty response")
        return _empty_response(request)

    _emit(emitter, "debug", "Retrieve", "POIs retrieved", {"count": len(pois)})

    # 1b. Refresh stale POIs (only triggers LLM for stale ones)
    from agentic_tour_planner.agents.freshness_agent import refresh_pois
    pois = await refresh_pois(pois, destination)

    # 2. Sequence into days
    _emit(emitter, "step", "Sequence", "Sequencing into days...")
    skeleton = sequence(pois, duration_days=days)
    _emit(emitter, "debug", "Sequence", "Sequenced", {"days": len(skeleton)})

    # 3. Get weather
    weather = {}
    try:
        weather_tool = WeatherTool()
        snapshot = await weather_tool.current_weather(destination)
        if snapshot:
            weather = {"summary": snapshot.summary, "temp_c": snapshot.temperature_c}
    except Exception as e:
        logger.warning("Weather fetch failed: {}".format(e))

    # 4. Run critique loop (cost -> budget critique -> timing critique -> revise)
    _emit(emitter, "step", "Critique", "Running critique loop...")
    state = TripState(
        trip_meta={
            "destination": destination,
            "travelers": travelers,
            "budget_tier": budget_tier,
            "duration_days": days,
            "daily_hour_budget": 8.0,
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

    # 7. Build response
    return _build_response(request, narration, skeleton, cost_summary, weather)


def _build_response(
    request: PlanningRequest,
    narration: dict[str, Any],
    skeleton: list[dict[str, Any]],
    cost_summary: dict[str, Any],
    weather: dict[str, Any],
) -> PlanningResponse:
    """Build a PlanningResponse from pipeline outputs."""
    # Build DayPlan for each day
    itinerary = []
    narration_days = {d["day"]: d for d in narration.get("days", [])}

    for day in skeleton:
        day_num = day.get("day", 0)
        narration_day = narration_days.get(day_num, {})

        spots = []
        for poi in day.get("pois", []):
            spot = SpotDetail(
                name=poi.get("name", "Unknown"),
                lat=poi.get("lat"),
                lon=poi.get("long"),
                description=poi.get("long_description", ""),
                opening_hours=poi.get("hours"),
            )
            spots.append(spot)

        day_plan = DayPlan(
            day=day_num,
            theme=narration_day.get("narrative", "")[:100] if narration_day.get("narrative") else day.get("city", "Day {}".format(day_num)),
            summary=narration_day.get("narrative"),
            spots=spots,
            weather=DayWeather(summary=weather.get("summary", "")) if weather else None,
        )
        itinerary.append(day_plan)

    # Build cost estimate
    cost_estimate = None
    if cost_summary:
        daily_costs = []
        for day_cost in cost_summary.get("daily_costs", []):
            items = [
                CostLineItem(label=item.get("description", "?"), amount=float(item.get("amount", 0)))
                for item in day_cost.get("items", [])
            ]
            daily_costs.append(DailyCost(
                day=day_cost.get("day", 0),
                items=items,
                subtotal=float(day_cost.get("day_total_all_travelers", 0)),
            ))

        cost_estimate = CostEstimate(
            daily=daily_costs,
            overall=OverallCost(
                grand_total=cost_summary.get("grand_total"),
                per_person_total=cost_summary.get("per_person_total"),
                members=cost_summary.get("travelers", 1),
            ),
        )

    return PlanningResponse(
        overview=narration.get("overview", "Trip plan for {}".format(request.destination)),
        itinerary=itinerary,
        practical_tips=narration.get("general_tips", []),
        citations=[Citation(title="Wikivoyage", url="https://en.wikivoyage.org")],
        insights=_build_minimal_insights(request),
        provider_used="pipeline-v2",
        model_used="hybrid-graph-vector",
        monthly_weather=weather.get("summary"),
        transport_options=[],
        cost_estimate=cost_estimate,
    )


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
