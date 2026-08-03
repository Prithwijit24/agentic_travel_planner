from agentic_tour_planner.domain.models import DayPlan, PlanningRequest, SpotDetail
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline
from agentic_tour_planner.pipeline.prompts import (
    DAY_REALIGN_SYSTEM_PROMPT,
    build_day_realign_prompt,
)


def _day(num: int, spot_names: list[tuple[str, float, float]]) -> DayPlan:
    spots = [SpotDetail(name=name, lat=lat, lon=lon) for name, lat, lon in spot_names]
    return DayPlan(day=num, theme=f"Old theme {num}", spots=spots)


def _request() -> PlanningRequest:
    return PlanningRequest(
        destination="Gangtok",
        trip_length_days=2,
        budget_level="midrange",
    )


def test_realign_system_prompt_forces_json_only():
    assert '"theme"' in DAY_REALIGN_SYSTEM_PROMPT
    assert '"summary"' in DAY_REALIGN_SYSTEM_PROMPT
    assert '"hotel_recommendation"' in DAY_REALIGN_SYSTEM_PROMPT
    assert '"needs_hotel_change"' in DAY_REALIGN_SYSTEM_PROMPT
    assert "every place" in DAY_REALIGN_SYSTEM_PROMPT


def test_realign_prompt_contains_final_places():
    prompt = build_day_realign_prompt(
        _request(),
        day_num=2,
        day_places=["Enchey Monastery", "Tsomgo Lake"],
        prev_day_places=["MG Marg"],
        budget_level="midrange",
    )
    assert "Enchey Monastery" in prompt
    assert "Tsomgo Lake" in prompt
    assert "MG Marg" in prompt
    assert "Day 2" in prompt


def test_apply_realign_updates_narrative_fields_only():
    pipeline = AgenticTourPlannerPipeline.__new__(AgenticTourPlannerPipeline)
    day = _day(1, [("A", 27.3, 88.6)])
    result = {
        "theme": "Monasteries & Alpine Lakes",
        "summary": "Enchey Monastery and Tsomgo Lake are covered today.",
        "hotel_recommendation": "Stay near the MG Marg for walkability.",
        "needs_hotel_change": True,
    }
    AgenticTourPlannerPipeline._apply_realign(day, result)
    assert day.theme == "Monasteries & Alpine Lakes"
    assert day.summary.startswith("Enchey Monastery")
    assert day.hotel_recommendation == "Stay near the MG Marg for walkability."
    assert day.needs_hotel_change is True
    assert [s.name for s in day.spots] == ["A"]


def test_apply_realign_ignores_malformed_values():
    pipeline = AgenticTourPlannerPipeline.__new__(AgenticTourPlannerPipeline)
    day = _day(1, [("A", 27.3, 88.6)])
    AgenticTourPlannerPipeline._apply_realign(day, {"theme": "", "needs_hotel_change": "yes"})
    assert day.theme == "Old theme 1"
    assert day.needs_hotel_change is False


def test_fallback_day_realign_derives_theme_from_anchor_spot():
    pipeline = AgenticTourPlannerPipeline.__new__(AgenticTourPlannerPipeline)
    day = _day(1, [("Tsomgo Lake", 27.37, 88.75), ("Baba Mandir", 27.39, 88.78)])
    pipeline._fallback_day_realign(_request(), [day], 0)
    assert "Tsomgo Lake" in day.theme
    assert "Tsomgo Lake" in day.summary
    assert "Stay centrally in the Tsomgo Lake area" in day.hotel_recommendation
    assert day.needs_hotel_change is False


def test_day_centroid_moved_flags_far_days():
    pipeline = AgenticTourPlannerPipeline.__new__(AgenticTourPlannerPipeline)
    itinerary = [
        _day(1, [("MG Marg", 27.33, 88.61)]),
        _day(2, [("Tsomgo Lake", 27.37, 89.05)]),
    ]
    assert AgenticTourPlannerPipeline._day_centroid_moved(itinerary, 0) is False
    assert AgenticTourPlannerPipeline._day_centroid_moved(itinerary, 1) is True


def test_day_centroid_moved_no_coords_is_false():
    pipeline = AgenticTourPlannerPipeline.__new__(AgenticTourPlannerPipeline)
    itinerary = [
        DayPlan(day=1, theme="t", spots=[SpotDetail(name="A")]),
        DayPlan(day=2, theme="t", spots=[SpotDetail(name="B")]),
    ]
    assert AgenticTourPlannerPipeline._day_centroid_moved(itinerary, 1) is False
