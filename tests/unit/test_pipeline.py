from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    DayPlan,
    PlanningInsights,
    PlanningRequest,
    RetrievedContext,
    RouteGuidance,
    SpotDetail,
    TimingGuidance,
)
from agentic_tour_planner.pipeline.place_constraints import enforce_minimum_daily_spots
from agentic_tour_planner.pipeline.prompts import build_itinerary_prompt


def test_prompt_contains_request_details():
    request = PlanningRequest(destination="Kyoto", trip_length_days=4, interests=["food", "temples"])
    context = RetrievedContext()
    insights = PlanningInsights(
        route=RouteGuidance(strategy="direct"),
        budget=BudgetGuidance(estimated_daily_budget=100, estimated_total_budget=400),
        timing=TimingGuidance(season_summary="mild", booking_window="2 weeks"),
    )

    prompt = build_itinerary_prompt(request, context, insights)

    assert "Kyoto" in prompt
    assert "food, temples" in prompt


def test_day_plan_accepts_rationale():
    day = DayPlan(day=1, theme="North cluster", rationale="Covers nearby northern places and returns to base.")

    assert day.rationale == "Covers nearby northern places and returns to base."


def test_prompt_requires_geographic_travel_constraints():
    request = PlanningRequest(destination="Sikkim", trip_length_days=4, places_per_day="4-6")
    context = RetrievedContext()
    insights = PlanningInsights(
        route=RouteGuidance(strategy="cluster by region"),
        budget=BudgetGuidance(estimated_daily_budget=100, estimated_total_budget=400),
        timing=TimingGuidance(season_summary="clear", booking_window="2 weeks"),
    )

    prompt = build_itinerary_prompt(request, context, insights)

    assert "GEOGRAPHIC CLUSTERING FIRST" in prompt
    assert "3-4 hours" in prompt
    assert "50-70 km" in prompt
    assert "1.5 hours" in prompt
    assert "Day N+1 must logically start" in prompt
    assert "multi-city" in prompt
    assert "rationale" in prompt
    assert "4-6 recommended/core places" in prompt
    assert "above 6" in prompt


def test_enforces_requested_minimum_spots_per_regular_day():
    request = PlanningRequest(destination="Sikkim", trip_length_days=3, places_per_day="4-6")
    itinerary = [
        DayPlan(
            day=1,
            theme="Monasteries",
            morning=["Visit Rumtek Monastery (Morning 8:00-9:30)"],
            afternoon=["Explore Namgyal Institute of Tibetology (Afternoon 14:00-15:30)"],
            evening=["Walk MG Marg (Evening 19:00-20:30)"],
            spots=[SpotDetail(name="Rumtek Monastery")],
        ),
        DayPlan(day=3, theme="Departure / Return Travel", spots=[]),
    ]

    enforced = enforce_minimum_daily_spots(request, itinerary)

    assert len(enforced[0].spots) >= 4
    assert len(enforced[1].spots) >= 4


def test_uses_max_attractions_default_when_places_per_day_missing():
    request = PlanningRequest(destination="Kyoto", trip_length_days=2, max_attractions_per_day=5)
    itinerary = [
        DayPlan(
            day=1,
            theme="Temples",
            morning=["Visit Fushimi Inari Shrine (Morning 6:00-8:00)"],
            spots=[],
        ),
    ]

    enforced = enforce_minimum_daily_spots(request, itinerary)

    assert len(enforced[0].spots) >= 5
