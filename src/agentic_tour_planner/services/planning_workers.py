from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

import pydantic

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    PlanningInsights,
    PlanningRequest,
    RetrievedContext,
    RouteGuidance,
    TimingGuidance,
)
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def _safe_build(model_cls: type[T], heuristic: Callable[[], T], **fields: Any) -> T:
    """Validate LLM-produced fields into a pydantic model. If the model output
    parsed as JSON but violates the schema (common with small models), fall
    back to the heuristic instead of raising into the pipeline."""
    try:
        return model_cls(**fields)
    except pydantic.ValidationError as exc:
        logger.warning("LLM worker JSON failed schema validation, using heuristic fallback: {}", str(exc)[:120])
        return heuristic()


class RoutePlannerWorker:
    def __init__(self) -> None:
        self.llm = LLMProvider()
        logger.debug("RoutePlannerWorker initialized")

    async def build(
        self,
        request: PlanningRequest,
        context: RetrievedContext,
        provider_override: str | None = None,
    ) -> RouteGuidance:
        logger.info(
            "RoutePlannerWorker.build start destination={} days={} provider_override={}",
            request.destination,
            request.trip_length_days,
            provider_override,
        )

        days = request.trip_length_days
        if days <= 3:
            routing_directive = (
                "Keep the trip COMPACT: wander the nearer places around a single base; "
                "minimise long transfers between regions."
            )
        elif days <= 6:
            routing_directive = (
                "Cover the main sights AND include 1-2 offbeat / lesser-known places in addition to the popular ones."
            )
        elif days >= 11:
            routing_directive = (
                "Split the stay across TWO OR MORE distinct regions/areas of the destination "
                "(e.g. Andaman: first 5-6 days in one area, then move to a different region such "
                "as the north for the remaining days). Apply this region-split principle to any long trip."
            )
        else:
            routing_directive = (
                "Balance popular and offbeat sights; if the destination is large, consider a "
                "regional split so the trip stays coherent."
            )

        # Generate route guidance using LLM
        prompt = f"""
Generate route guidance for a {days}-day trip to {request.destination}.
Origin: {request.origin or "Not specified"}
Interests: {", ".join(request.interests) or "General sightseeing"}

MANDATORY ROUTING DIRECTIVE (you MUST follow this exactly):
{routing_directive}

Based on the available documents and context, provide:
1. A route strategy (1-2 sentences) that reflects the directive above
2. 3-5 cluster advice for grouping nearby attractions
3. Transit notes for efficient travel

Return JSON with keys: strategy, cluster_advice (list), transit_notes (list)
"""
        result = await self.llm.complete_structured(
            prompt, "route", provider_override=provider_override, model_override=request.worker_model
        )

        if "error" in result or not result:
            # Fallback to basic guidance
            logger.warning("RoutePlannerWorker.build fell back to heuristic guidance")
            return self._heuristic(request, routing_directive)

        logger.debug("RoutePlannerWorker.build done strategy_len={}", len(result.get("strategy", "")))
        return _safe_build(
            RouteGuidance,
            lambda: self._heuristic(request, routing_directive),
            strategy=result.get("strategy") or f"Navigate {request.destination} by geographic clusters.",
            cluster_advice=result.get("cluster_advice"),
            transit_notes=result.get("transit_notes"),
        )

    @staticmethod
    def _heuristic(request: PlanningRequest, routing_directive: str) -> RouteGuidance:
        return RouteGuidance(
            strategy=routing_directive,
            cluster_advice=[f"Group major sights in {request.destination} by neighborhood."],
            transit_notes=[
                "Start from transport hub first when arriving."
                if request.origin
                else "Anchor day one near city center.",
                "Group nearby attractions into walkable or single-transit corridors.",
            ],
        )


class BudgetPlannerWorker:
    def __init__(self) -> None:
        self.llm = LLMProvider()
        logger.debug("BudgetPlannerWorker initialized")

    @staticmethod
    def _daily_budgets():
        s = get_settings()
        return {
            "budget": s.worker_daily_budget_budget,
            "midrange": s.worker_daily_budget_midrange,
            "luxury": s.worker_daily_budget_luxury,
        }

    async def build(
        self,
        request: PlanningRequest,
        context: RetrievedContext,
        provider_override: str | None = None,
    ) -> BudgetGuidance:
        logger.info(
            "BudgetPlannerWorker.build start destination={} budget_level={} provider_override={}",
            request.destination,
            request.budget_level,
            provider_override,
        )
        prompt = f"""
Generate budget guidance for a {request.trip_length_days}-day {request.budget_level} trip to {request.destination}.
Interests: {", ".join(request.interests) or "General sightseeing"}
Travel month: {request.travel_month or "Flexible"}
Weather: {context.weather.summary if context.weather else "Not available"}

Return JSON with keys: estimated_daily_budget, estimated_total_budget, assumptions (list), saving_tips (list)
"""
        result = await self.llm.complete_structured(
            prompt, "budget", provider_override=provider_override, model_override=request.worker_model
        )

        if "error" in result or not result:
            # Fallback to calculated guidance
            logger.warning("BudgetPlannerWorker.build fell back to calculated guidance")
            return self._heuristic(request)

        logger.debug(
            "BudgetPlannerWorker.build done daily={} total={}",
            result.get("estimated_daily_budget"),
            result.get("estimated_total_budget"),
        )
        return _safe_build(
            BudgetGuidance,
            lambda: self._heuristic(request),
            estimated_daily_budget=result.get("estimated_daily_budget") or 160.0,
            estimated_total_budget=result.get("estimated_total_budget") or 640.0,
            assumptions=result.get("assumptions") or [],
            saving_tips=result.get("saving_tips") or [],
        )

    @staticmethod
    def _heuristic(request: PlanningRequest) -> BudgetGuidance:
        daily_budgets = BudgetPlannerWorker._daily_budgets()
        base = daily_budgets.get(request.budget_level, 160.0)
        multiplier = 1.0 + min(len(request.interests), 5) * 0.05
        daily = round(base * multiplier, 2)
        total = round(daily * request.trip_length_days, 2)

        return BudgetGuidance(
            estimated_daily_budget=daily,
            estimated_total_budget=total,
            assumptions=[
                "Estimate includes lodging, local transport, attraction tickets, and meals.",
                "Flight or long-haul rail to destination is excluded.",
            ],
            saving_tips=[
                "Reserve flagship attractions early to avoid surge pricing.",
                "Use neighborhood clusters to reduce repeated transit fares.",
            ],
        )


class TimingPlannerWorker:
    def __init__(self) -> None:
        self.llm = LLMProvider()
        logger.debug("TimingPlannerWorker initialized")

    @staticmethod
    def _high_season_months() -> set[str]:
        months = get_settings().worker_high_season_months
        return set(months) if months else {"june", "july", "august", "december"}

    async def build(
        self,
        request: PlanningRequest,
        context: RetrievedContext,
        provider_override: str | None = None,
    ) -> TimingGuidance:
        month = (request.travel_month or "").strip().lower()
        high_season = month in self._high_season_months()
        logger.info(
            "TimingPlannerWorker.build start destination={} travel_month={} provider_override={}",
            request.destination,
            request.travel_month,
            provider_override,
        )

        prompt = f"""
Generate timing guidance for a {request.trip_length_days}-day trip to {request.destination} in {request.travel_month or "Flexible"}.
Weather: {context.weather.summary if context.weather else "Not available"}
Place hours: {len(context.place_hours)} locations with opening hours available

Return JSON with keys: season_summary, booking_window, day_planning_notes (list)
"""
        result = await self.llm.complete_structured(
            prompt, "timing", provider_override=provider_override, model_override=request.worker_model
        )

        if "error" in result or not result:
            # Fallback to calculated guidance
            logger.warning("TimingPlannerWorker.build fell back to calculated guidance")
            return self._heuristic(request, context, high_season)

        logger.debug("TimingPlannerWorker.build done season_summary_len={}", len(result.get("season_summary", "")))
        return _safe_build(
            TimingGuidance,
            lambda: self._heuristic(request, context, high_season),
            season_summary=result.get("season_summary")
            or f"Plan for {request.travel_month or 'optimal timing'} in {request.destination}.",
            booking_window=result.get("booking_window") or "Book 4-8 weeks ahead.",
            day_planning_notes=result.get("day_planning_notes") or [],
        )

    @staticmethod
    def _heuristic(request: PlanningRequest, context: RetrievedContext, high_season: bool) -> TimingGuidance:
        season_summary = (
            f"{request.travel_month} is likely a busier travel month for {request.destination}."
            if high_season and request.travel_month
            else f"{request.travel_month or 'Your target month'} is likely manageable for balanced pacing in {request.destination}."
        )
        booking_window = (
            "Book 8-12 weeks ahead for lodging and high-demand tickets."
            if high_season
            else "Book 4-8 weeks ahead and recheck prices weekly."
        )
        notes = [
            "Front-load reservation-only sights earlier in the trip.",
            "Keep one flexible indoor block each day for weather or fatigue swings.",
        ]
        if context.place_hours:
            notes.append("Validate venue opening windows again 24 hours before the visit.")

        return TimingGuidance(
            season_summary=season_summary,
            booking_window=booking_window,
            day_planning_notes=notes,
        )


class PlanningInsightsBuilder:
    def __init__(self) -> None:
        self.route_worker = RoutePlannerWorker()
        self.budget_worker = BudgetPlannerWorker()
        self.timing_worker = TimingPlannerWorker()
        # Provider/model actually used per worker role on the last build.
        self.last_worker_used: dict[str, tuple[str, str]] = {}
        logger.debug("PlanningInsightsBuilder initialized")

    async def build(
        self,
        request: PlanningRequest,
        context: RetrievedContext,
        provider_override: str | None = None,
    ) -> PlanningInsights:
        logger.info(
            "PlanningInsightsBuilder.build start destination={} provider_override={}",
            request.destination,
            provider_override,
        )
        results = await asyncio.gather(
            self.route_worker.build(request, context, provider_override=provider_override),
            self.budget_worker.build(request, context, provider_override=provider_override),
            self.timing_worker.build(request, context, provider_override=provider_override),
        )
        route, budget, timing = results

        self.last_worker_used = {
            "route": self.route_worker.llm.last_worker_used(),
            "budget": self.budget_worker.llm.last_worker_used(),
            "timing": self.timing_worker.llm.last_worker_used(),
        }

        logger.debug("PlanningInsightsBuilder.build done workers={}", self.last_worker_used)
        return PlanningInsights(
            route=route,
            budget=budget,
            timing=timing,
        )
