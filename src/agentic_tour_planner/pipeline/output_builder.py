"""Shared output builder for CLI and API to ensure consistent output structure."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentic_tour_planner.domain.models import (
        DetailedPlan,
        PlanningInsights,
        PlanningRequest,
        PlanningResponse,
        RetrievedContext,
    )
    from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline

logger = logging.getLogger(__name__)

TARGET_DESCRIPTION_WORDS = 200
WORD_COUNT_TOLERANCE = 20  # ±20 words from target (180-220 words)


def _validate_place_word_counts(detailed: DetailedPlan | None) -> list[str]:
    """Check that each place description is approximately TARGET_DESCRIPTION_WORDS."""
    warnings: list[str] = []
    if not detailed:
        return warnings
    for day in detailed.days or []:
        for place in day.places or []:
            desc = place.description or ""
            word_count = len(desc.split())
            if abs(word_count - TARGET_DESCRIPTION_WORDS) > WORD_COUNT_TOLERANCE:
                warnings.append(
                    f"Place '{place.name}' description has {word_count} words (target ~{TARGET_DESCRIPTION_WORDS})"
                )
    return warnings


def build_output(
    request: PlanningRequest,
    context: RetrievedContext,
    insights: PlanningInsights,
    response: PlanningResponse,
    detailed: DetailedPlan | None = None,
    pipeline: AgenticTourPlannerPipeline | None = None,
    metrics: dict | None = None,
    profile_rows: list[dict] | None = None,
) -> dict[str, Any]:
    """Build the unified output dictionary used by both CLI and API.

    This ensures the output structure is identical regardless of the caller.
    """
    word_warnings = _validate_place_word_counts(detailed)
    for w in word_warnings:
        logger.warning(w)

    return {
        "request": request.model_dump(mode="json"),
        "context": {
            "documents_count": len(context.documents),
            "search_results_count": len(context.search_results),
            "place_hours_count": len(context.place_hours),
            "weather": context.weather.summary if context.weather else None,
        },
        "insights": {
            "route": {
                "strategy": insights.route.strategy,
                "cluster_advice": insights.route.cluster_advice,
                "transit_notes": insights.route.transit_notes,
            },
            "budget": {
                "estimated_daily_budget": insights.budget.estimated_daily_budget,
                "estimated_total_budget": insights.budget.estimated_total_budget,
                "assumptions": insights.budget.assumptions,
                "saving_tips": insights.budget.saving_tips,
            },
            "timing": {
                "season_summary": insights.timing.season_summary,
                "booking_window": insights.timing.booking_window,
                "day_planning_notes": insights.timing.day_planning_notes,
            },
        },
        "response": {
            "plan_id": response.plan_id,
            "overview": response.overview,
            "monthly_weather": response.monthly_weather,
            "travel_month": request.travel_month,
            "transport_options": [t.model_dump() for t in response.transport_options],
            "cost_estimate": response.cost_estimate.model_dump() if response.cost_estimate else None,
            "itinerary": [day.model_dump() for day in response.itinerary],
            "practical_tips": response.practical_tips,
            "citations": [c.model_dump() for c in response.citations],
            "provider_used": response.provider_used,
            "model_used": response.model_used,
            "worker_provider_used": response.worker_provider_used,
            "worker_model_used": response.worker_model_used,
            "live_web_brief": response.live_web_brief.model_dump() if response.live_web_brief else None,
            "worker_routing": pipeline.insights_builder.last_worker_used if pipeline else None,
            "generated_at": response.generated_at,
            "metrics": metrics,
        },
        "detailed": detailed.model_dump() if detailed else None,
        "profile": profile_rows or [],
    }
