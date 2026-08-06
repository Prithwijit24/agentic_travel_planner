"""Tests for the deterministic cost estimator.

The estimator is computed from the plan structure + trip inputs using a fixed
price table. It never touches an LLM, so it always returns concrete numbers
(no "N/A" cost card when model gateways are down).
"""

import asyncio

from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.services.cost_estimator import CostEstimator


def _make_request(travelers: int = 4, budget: str = "midrange") -> PlanningRequest:
    return PlanningRequest(
        destination="Sikkim",
        origin="Kolkata",
        trip_length_days=4,
        interests=["nature", "monasteries"],
        budget_level=budget,
        travel_month="September",
        transport_mode="public",
        travelers=travelers,
    )


def _plan() -> dict:
    return {
        "itinerary": [
            {
                "day": 1,
                "theme": "Gangtok",
                "spots": [
                    {"name": "MG Marg", "lat": 27.3314, "lon": 88.6138},
                    {"name": "Rumtek Monastery", "lat": 27.2857, "lon": 88.5615},
                    {"name": "Namchi Char Dham", "lat": 27.1650, "lon": 88.3500},
                ],
            },
            {
                "day": 2,
                "theme": "Pelling",
                "spots": [
                    {"name": "Khecheopalri Lake", "lat": 27.3617, "lon": 88.2130},
                    {"name": "Pelling Skywalk", "lat": 27.3010, "lon": 88.2170},
                ],
            },
            {
                "day": 3,
                "theme": "Ravangla",
                "spots": [{"name": "Ravangla Buddha Park", "lat": 27.3050, "lon": 88.3630}],
            },
            {"day": 4, "theme": "Departure", "morning": ["Drive to airport"], "spots": []},
        ]
    }


def test_deterministic_estimate_matches_price_table():
    result = asyncio.run(CostEstimator().estimate(_make_request(), _plan()))

    assert result.overall is not None
    # 4 people, 2 rooms, midrange: hotel 1500/night, food 600/person, public transport 80/leg.
    # Day 1: 3 spots -> hotel 3000 + food 2400 + transport 80*3*4=960 + tickets (100+600+100)*4=3200 = 9560
    # Day 2: 2 spots -> hotel 3000 + food 2400 + transport 640 + tickets (300+100)*4=1600 = 7640
    # Day 3: 1 spot  -> hotel 3000 + food 2400 + transport 320 + tickets 300*4=1200 = 6920
    # Day 4: 1 activity -> hotel 3000 + food 2400 + transport 320 + tickets 400 = 6120
    # Grand 30240, per person 7560.
    assert result.overall.grand_total == 30240.0
    assert result.overall.per_person_total == 7560.0
    assert result.overall.members == 4
    assert [d.subtotal for d in result.daily] == [9560.0, 7640.0, 6920.0, 6120.0]

    assert result.daily[0].items[0].label == "Hotel (1500 x 2 room(s))"
    assert result.daily[0].items[0].amount == 3000.0
    assert result.daily[0].items[-1].label == "Entry tickets (3 place(s) x 4 people)"


def test_no_na_always_concrete_totals():
    result = asyncio.run(CostEstimator().estimate(_make_request(travelers=1), _plan()))
    assert result.overall is not None
    assert result.overall.per_person_total is not None
    assert result.overall.grand_total is not None


def test_caps_daily_cost_at_8000_per_person():
    # Luxury, solo traveller, all 8 major sites in one day:
    # hotel 3000 + food 1200 + transport 150*8 + tickets 600*8 = 10200 per person -> capped at 8000.
    request = _make_request(travelers=1, budget="luxury")
    plan = {
        "itinerary": [
            {
                "day": 1,
                "spots": [{"name": f"Major {i} Temple", "lat": float(i), "lon": 0.0} for i in range(8)],
            }
        ]
    }
    result = asyncio.run(CostEstimator().estimate(request, plan))
    assert result.daily[0].subtotal == 8000.0
    assert "capped" in result.daily[0].steps[-1]


def test_empty_itinerary_yields_zero():
    result = asyncio.run(CostEstimator().estimate(_make_request(), {"itinerary": []}))
    assert result.overall is not None
    assert result.overall.grand_total == 0.0
    assert result.overall.per_person_total == 0.0


def test_ticket_tier_by_place_name():
    request = _make_request(travelers=1)
    plan = {
        "itinerary": [
            {"day": 1, "spots": [{"name": "Gangtok Monastery"}, {"name": "Temi Tea Garden"}, {"name": "MG Marg"}]}
        ]
    }
    result = asyncio.run(CostEstimator().estimate(request, plan))
    # Monastery=600, garden=300, MG Marg=100 -> 1000 x 1 person.
    tickets = next(i for i in result.daily[0].items if i.label.startswith("Entry tickets"))
    assert tickets.amount == 1000.0
