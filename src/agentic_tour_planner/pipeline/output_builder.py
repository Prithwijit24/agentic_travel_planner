"""Shared output builder for CLI and API to ensure consistent output structure."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agentic_tour_planner.config.settings import get_settings

if TYPE_CHECKING:
    from agentic_tour_planner.domain.models import (
        DetailedPlan,
        PlaceImage,
        PlanningInsights,
        PlanningRequest,
        PlanningResponse,
        RetrievedContext,
    )

logger = logging.getLogger(__name__)


def _word_count_settings():
    s = get_settings()
    return s.pipeline_target_description_words, s.pipeline_word_count_tolerance


def _validate_place_word_counts(detailed: DetailedPlan | None) -> list[str]:
    """Check that each place description is approximately TARGET_DESCRIPTION_WORDS."""
    target_description_words, word_count_tolerance = _word_count_settings()
    warnings: list[str] = []
    if not detailed:
        return warnings
    for day in detailed.days or []:
        for place in day.places or []:
            desc = place.description or ""
            word_count = len(desc.split())
            if abs(word_count - target_description_words) > word_count_tolerance:
                warnings.append(
                    f"Place '{place.name}' description has {word_count} words (target ~{target_description_words})"
                )
    return warnings


def build_output(
    request: PlanningRequest,
    context: RetrievedContext,
    insights: PlanningInsights,
    response: PlanningResponse,
    detailed: DetailedPlan | None = None,
    metrics: dict | None = None,
    profile_rows: list[dict] | None = None,
    images: list[PlaceImage] | None = None,
) -> dict[str, Any]:
    """Build the unified output dictionary used by both CLI and API.

    This ensures the output structure is identical regardless of the caller.
    """
    word_warnings = _validate_place_word_counts(detailed)
    for w in word_warnings:
        logger.warning(w)

    worker_routing = None
    if response.worker_provider_used and response.worker_model_used:
        worker_routing = {"planner": (response.worker_provider_used, response.worker_model_used)}

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
            "worker_routing": worker_routing,
            "generated_at": response.generated_at,
            "metrics": metrics,
        },
        "detailed": detailed.model_dump() if detailed else None,
        "images": [img.model_dump() for img in images] if images else [],
        "profile": profile_rows or [],
    }
