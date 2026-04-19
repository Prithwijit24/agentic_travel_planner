from __future__ import annotations

from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    PlanningInsights,
    PlanningRequest,
    RetrievedContext,
    RouteGuidance,
    TimingGuidance,
)


class RoutePlannerWorker:
    def build(self, request: PlanningRequest, context: RetrievedContext) -> RouteGuidance:
        clustered = []
        for document in context.documents[:3]:
            clustered.append(f"Cluster activities around evidence from {document.title}.")
        transit = [
            f"Start from {request.origin} transport hub first when arriving." if request.origin else "Anchor day one near the city center.",
            "Group nearby attractions into walkable or single-transit corridors.",
        ]
        return RouteGuidance(
            strategy=f"Build each day around one zone of {request.destination} to limit transit churn.",
            cluster_advice=clustered or [f"Group major sights in {request.destination} by neighborhood."],
            transit_notes=transit,
        )


class BudgetPlannerWorker:
    DAILY_BUDGETS = {"budget": 70.0, "midrange": 160.0, "luxury": 320.0}

    def build(self, request: PlanningRequest, context: RetrievedContext) -> BudgetGuidance:
        base = self.DAILY_BUDGETS[request.budget_level]
        multiplier = 1.0 + min(len(request.interests), 5) * 0.05
        daily = round(base * multiplier, 2)
        total = round(daily * request.trip_length_days, 2)
        assumptions = [
            "Estimate includes lodging, local transport, attraction tickets, and meals.",
            "Flight or long-haul rail to destination is excluded unless explicitly noted.",
        ]
        if context.weather:
            assumptions.append("Weather-driven taxi or rideshare usage may increase transport cost.")
        tips = [
            "Reserve flagship attractions early to avoid surge pricing.",
            "Use neighborhood clusters to reduce repeated transit fares.",
        ]
        return BudgetGuidance(
            estimated_daily_budget=daily,
            estimated_total_budget=total,
            assumptions=assumptions,
            saving_tips=tips,
        )


class TimingPlannerWorker:
    HIGH_SEASON_MONTHS = {
        "june", "july", "august", "december",
    }

    def build(self, request: PlanningRequest, context: RetrievedContext) -> TimingGuidance:
        month = (request.travel_month or "").strip().lower()
        high_season = month in self.HIGH_SEASON_MONTHS
        season_summary = (
            f"{request.travel_month} is likely a busier travel month for {request.destination}."
            if high_season and request.travel_month
            else f"{request.travel_month or 'Your target month'} is likely manageable for balanced pacing in {request.destination}."
        )
        booking_window = "Book 8-12 weeks ahead for lodging and high-demand tickets." if high_season else "Book 4-8 weeks ahead and recheck prices weekly."
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

    def build(self, request: PlanningRequest, context: RetrievedContext) -> PlanningInsights:
        return PlanningInsights(
            route=self.route_worker.build(request, context),
            budget=self.budget_worker.build(request, context),
            timing=self.timing_worker.build(request, context),
        )

