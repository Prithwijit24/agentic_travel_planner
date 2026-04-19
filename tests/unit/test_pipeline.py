from agentic_tour_planner.domain.models import PlanningRequest, RetrievedContext
from agentic_tour_planner.pipeline.prompts import build_itinerary_prompt
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder


def test_prompt_contains_request_details():
    request = PlanningRequest(destination="Kyoto", trip_length_days=4, interests=["food", "temples"])
    context = RetrievedContext()
    insights = PlanningInsightsBuilder().build(request, context)

    prompt = build_itinerary_prompt(request, context, insights)

    assert "Kyoto" in prompt
    assert "food, temples" in prompt

