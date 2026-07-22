import pytest

from agentic_tour_planner.domain.models import DayPlan, PlanningRequest, SpotDetail
from agentic_tour_planner.pipeline.travel_constraints import TravelLeg, annotate_travel_constraints


@pytest.mark.asyncio
async def test_annotates_long_adjacent_leg(monkeypatch):
    async def fake_lookup(origin: str, destination: str, request: PlanningRequest):
        return TravelLeg(origin=origin, destination=destination, distance_km=95.0, duration_minutes=130)

    monkeypatch.setattr("agentic_tour_planner.pipeline.travel_constraints.lookup_travel_leg", fake_lookup)
    request = PlanningRequest(destination="Sikkim", trip_length_days=1)
    itinerary = [
        DayPlan(
            day=1,
            theme="Spread out",
            spots=[SpotDetail(name="Gangtok"), SpotDetail(name="Pelling")],
        )
    ]

    result = await annotate_travel_constraints(request, itinerary)

    warning_text = " ".join(result[0].logistics)
    assert "far apart" in warning_text
    assert "95 km" in warning_text
    assert "130 min" in warning_text
    assert result[0].rationale is not None
    assert "significant travel time" in result[0].rationale


@pytest.mark.asyncio
async def test_annotates_over_daily_travel_budget(monkeypatch):
    legs = {
        ("A", "B"): TravelLeg(origin="A", destination="B", distance_km=40.0, duration_minutes=100),
        ("B", "C"): TravelLeg(origin="B", destination="C", distance_km=45.0, duration_minutes=100),
        ("C", "D"): TravelLeg(origin="C", destination="D", distance_km=45.0, duration_minutes=80),
    }

    async def fake_lookup(origin: str, destination: str, request: PlanningRequest):
        return legs[(origin, destination)]

    monkeypatch.setattr("agentic_tour_planner.pipeline.travel_constraints.lookup_travel_leg", fake_lookup)
    request = PlanningRequest(destination="Testland", trip_length_days=1)
    itinerary = [
        DayPlan(
            day=1,
            theme="Heavy day",
            spots=[
                SpotDetail(name="A"),
                SpotDetail(name="B"),
                SpotDetail(name="C"),
                SpotDetail(name="D"),
            ],
        )
    ]

    result = await annotate_travel_constraints(request, itinerary)

    warning_text = " ".join(result[0].logistics)
    assert "daily travel budget" in warning_text
    assert "280 min" in warning_text
    assert "4 hours" in warning_text
