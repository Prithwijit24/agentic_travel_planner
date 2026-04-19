from agentic_tour_planner.domain.models import PlanningRequest, RetrievedContext
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder


def test_planning_insights_builder_generates_route_budget_and_timing():
    builder = PlanningInsightsBuilder()
    request = PlanningRequest(
        destination="Kyoto",
        trip_length_days=4,
        interests=["temples", "food"],
        budget_level="mid-range",
        travel_month="October",
        include_live_data=False,
    )

    insights = builder.build(request, RetrievedContext())

    strategy = insights.route.strategy.lower()
    assert "zone" in strategy or "cluster" in strategy or "district" in strategy
    assert insights.budget.estimated_daily_budget > 0
    assert "Book" in insights.timing.booking_window

