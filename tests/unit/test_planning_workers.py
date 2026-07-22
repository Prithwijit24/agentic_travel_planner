import asyncio

from agentic_tour_planner.domain.models import PlanningRequest, RetrievedContext
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder


def test_planning_insights_builder_generates_route_budget_and_timing():
    builder = PlanningInsightsBuilder()
    request = PlanningRequest(
        destination="Kyoto",
        trip_length_days=4,
        interests=["temples", "food"],
        budget_level="midrange",
        travel_month="October",
        include_live_data=False,
    )

    insights = asyncio.run(builder.build(request, RetrievedContext()))

    # Check that insights are generated (non-empty strings, positive budget)
    assert insights.route.strategy, "Route strategy should not be empty"
    assert len(insights.route.cluster_advice) > 0, "Should have cluster advice"
    assert len(insights.route.transit_notes) > 0, "Should have transit notes"
    assert insights.budget.estimated_daily_budget > 0, "Daily budget should be positive"
    assert insights.budget.estimated_total_budget > 0, "Total budget should be positive"
    assert insights.timing.booking_window, "Booking window should not be empty"
    assert insights.timing.season_summary, "Season summary should not be empty"
