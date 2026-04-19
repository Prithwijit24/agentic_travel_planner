from __future__ import annotations

from textwrap import dedent

from agentic_tour_planner.domain.models import PlanningInsights, PlanningRequest, RetrievedContext


def build_itinerary_prompt(request: PlanningRequest, context: RetrievedContext, insights: PlanningInsights) -> str:
    evidence_blocks: list[str] = []
    for document in context.documents:
        evidence_blocks.append(
            f"[Document] {document.title}\nURL: {document.url}\nContent: {document.content[:800]}"
        )
    for result in context.search_results:
        evidence_blocks.append(
            f"[Search] {result.title}\nURL: {result.url}\nSnippet: {result.snippet}"
        )
    for place in context.place_hours:
        evidence_blocks.append(
            f"[Place Hours] {place.venue}\nStatus: {place.status}\nHours: {' | '.join(place.opening_hours)}"
        )
    if context.weather:
        evidence_blocks.append(f"[Weather] {context.weather.summary}")

    guidance = dedent(
        f"""
        Route strategy: {insights.route.strategy}
        Route clusters: {'; '.join(insights.route.cluster_advice)}
        Transit notes: {'; '.join(insights.route.transit_notes)}
        Daily budget: {insights.budget.estimated_daily_budget}
        Total budget: {insights.budget.estimated_total_budget}
        Budget assumptions: {'; '.join(insights.budget.assumptions)}
        Savings tips: {'; '.join(insights.budget.saving_tips)}
        Timing summary: {insights.timing.season_summary}
        Booking window: {insights.timing.booking_window}
        Timing notes: {'; '.join(insights.timing.day_planning_notes)}
        """
    ).strip()

    return dedent(
        f"""
        You are producing a precise travel plan for {request.destination}.
        Respect the following input:
        Origin: {request.origin or 'Not specified'}
        Trip length: {request.trip_length_days} days
        Interests: {', '.join(request.interests) or 'General sightseeing'}
        Budget level: {request.budget_level}
        Travel month: {request.travel_month or 'Flexible'}
        Notes: {request.notes or 'None'}
        Max attractions per day: {request.max_attractions_per_day}

        Use this guidance:
        {guidance}

        Use this evidence:
        {'\n\n'.join(evidence_blocks) or 'No external evidence available.'}

        Return JSON with keys:
        overview, itinerary, practical_tips, citations.
        Itinerary must be a list of day objects with:
        day, theme, morning, afternoon, evening, meals, logistics.
        Citations must be grounded in the evidence above.
        """
    ).strip()

