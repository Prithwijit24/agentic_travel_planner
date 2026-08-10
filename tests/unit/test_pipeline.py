from typing import ClassVar

from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    DayPlan,
    PlanningInsights,
    PlanningRequest,
    RetrievedContext,
    RouteGuidance,
    TimingGuidance,
)
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


def test_prompt_softens_places_per_day_to_preference_not_quota():
    request = PlanningRequest(destination="Sikkim", trip_length_days=3, places_per_day="4-6")
    context = RetrievedContext()
    insights = PlanningInsights(
        route=RouteGuidance(strategy="cluster by region"),
        budget=BudgetGuidance(estimated_daily_budget=100, estimated_total_budget=400),
        timing=TimingGuidance(season_summary="clear", booking_window="2 weeks"),
    )

    prompt = build_itinerary_prompt(request, context, insights)

    # The places-per-day ask is now a soft target, never a hard minimum.
    assert "SOFT TARGET" in prompt
    assert "preference, not a quota" in prompt
    assert "STRICT MINIMUM" not in prompt
    assert "never pad a day with" in prompt


def test_strip_place_markdown_cleans_emphasis():
    from agentic_tour_planner.pipeline.prompts import strip_place_markdown

    assert strip_place_markdown("**Nathula Pass**") == "Nathula Pass"
    assert strip_place_markdown("  *MG Marg*  ") == "MG Marg"
    assert strip_place_markdown("plain name") == "plain name"
    assert strip_place_markdown("") == ""



    class Response:
        itinerary: ClassVar[list] = [
            {"day": 1, "spots": [{"name": "MG Marg"}, {"name": "Enchey Monastery"}, {"name": "Do Drul Chorten"}]},
            {"day": 3, "spots": [{"name": "Tsomgo Lake"}, {"name": "Baba Mandir"}]},
        ]

    raw = [
        {"day": 1, "places": [{"name": "MG Marg"}, {"name": "Enchey Monastery"}]},
        {
            "day": 3,
            "places": [
                {"name": "Tsomgo Lake"},
                {"name": "Baba Mandir"},
                # Already scheduled on Day 1 — must be dropped (even with "(optional)").
                {"name": "Enchey Monastery (optional)"},
                # Already scheduled on Day 1 with markdown name — must be dropped + cleaned.
                {"name": "**Do Drul Chorten**"},
                # Same-day repeat — must be dropped.
                {"name": "Tsomgo Lake"},
                # New place not scheduled elsewhere — kept.
                {"name": "Nathula Pass"},
            ],
        },
    ]


def test_detailed_prompt_contains_dedupe_and_plain_name_rules():
    from agentic_tour_planner.domain.models import DayPlan, PlanningRequest
    from agentic_tour_planner.pipeline.prompts import build_detailed_places_prompt

    request = PlanningRequest(destination="Sikkim", trip_length_days=6, interests=["landmarks"], places_per_day="3-5")

    class Response:
        itinerary: ClassVar[list] = [
            DayPlan(day=1, theme="Gangtok", spots=[{"name": "MG Marg"}, {"name": "Enchey Monastery"}]),
            DayPlan(day=3, theme="Tsomgo", spots=[{"name": "Tsomgo Lake"}, {"name": "Baba Mandir"}]),
        ]

    class Insights:
        class Route:
            strategy = "cluster by region"
            cluster_advice: ClassVar[list] = []
            transit_notes: ClassVar[list] = []

        class Budget:
            assumptions: ClassVar[list] = []

        route = Route()
        budget = Budget()

    prompt = build_detailed_places_prompt(request, Response(), None, {}, Insights(), target_day=3)

    assert "ALREADY SCHEDULED ON OTHER DAYS" in prompt
    assert "Enchey Monastery" in prompt
    assert "STRICT DEDUPE" in prompt
    assert "PLAIN TEXT" in prompt
