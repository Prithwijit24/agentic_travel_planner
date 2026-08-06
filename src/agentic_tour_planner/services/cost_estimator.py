"""
cost_estimator.py
=================
Deterministic travel cost estimation for a generated plan.

The estimate is computed from the plan's day structure (number of days, spots
per day) and the trip's fixed inputs (budget level, traveller count) using the
price table below. No LLM is involved, so the result is always present,
reproducible, and never a "N/A" card when the model gateways are down.

Price model (conservative lower ends of the ranges previously given to the LLM):
    HOTEL per room per night:  budget 800 | midrange 1500 | premium 3000
    FOOD per person per day:   budget 250 | midrange 600  | premium 1200
    LOCAL TRANSPORT per leg per person: 80 (public/unspecified) | 150 (car)
    ENTRY TICKETS per person per spot:  major 600 | popular 300 | local 100
    CAP: max 8000 per person per day

Hotel is per ROOM (1-2 people share a room); food, transport and tickets are
per person.
"""

from __future__ import annotations

import math
from typing import Any

from agentic_tour_planner.domain.models import (
    CostEstimate,
    CostLineItem,
    DailyCost,
    OverallCost,
    PlanningRequest,
)
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_HOTEL_RATE = {"budget": 800.0, "midrange": 1500.0, "luxury": 3000.0}
_FOOD_RATE = {"budget": 250.0, "midrange": 600.0, "luxury": 1200.0}
_TRANSPORT_RATE = {"public": 80.0, "car": 150.0}
_MAX_DAILY_PER_PERSON = 8000.0

_MAJOR_MARKERS = (
    "temple",
    "monastery",
    "palace",
    "fort",
    "museum",
    "waterfall",
    "falls",
    "peak",
    "trek",
    "sanctuary",
    "reserve",
    "monument",
    "valley",
    "national park",
)
_POPULAR_MARKERS = (
    "garden",
    "market",
    "bazaar",
    "viewpoint",
    "view point",
    "lake",
    "beach",
    "bridge",
    "square",
    "statue",
    "gallery",
    "ridge",
    "ghat",
    "island",
    "station",
    "church",
    "mosque",
    "tower",
    "hill",
    "cave",
    "point",
    "park",
)


def _ticket_price(name: str) -> float:
    n = (name or "").lower()
    if any(m in n for m in _MAJOR_MARKERS):
        return 600.0
    if any(m in n for m in _POPULAR_MARKERS):
        return 300.0
    return 100.0


class CostEstimator:
    async def estimate(self, request: PlanningRequest, plan_json: dict[str, Any]) -> CostEstimate:
        logger.info(
            "estimate start destination={} members={} days={}",
            request.destination,
            request.travelers,
            len(plan_json.get("itinerary", []) or []),
        )

        members = max(int(request.travelers or 1), 1)
        rooms = max(1, math.ceil(members / 2))
        budget = (request.budget_level or "midrange").lower()
        hotel_rate = _HOTEL_RATE.get(budget, 1500.0)
        food_rate = _FOOD_RATE.get(budget, 600.0)
        transport_rate = _TRANSPORT_RATE.get((request.transport_mode or "").lower(), 80.0)

        daily: list[DailyCost] = []
        for d in plan_json.get("itinerary", []) or []:
            if not isinstance(d, dict):
                continue
            try:
                day_num = int(d.get("day", 0))
            except (TypeError, ValueError):
                day_num = 0

            spots = d.get("spots") or []
            place_names: list[str] = []
            for s in spots:
                name = s.get("name") if isinstance(s, dict) else str(s)
                place_names.append(str(name))
            if place_names:
                place_count = len(place_names)
                ticket_total: float = sum(_ticket_price(n) for n in place_names)
            else:
                place_count = sum(len(d.get(k) or []) for k in ("morning", "afternoon", "evening"))
                ticket_total = float(place_count) * 100.0

            legs = max(place_count, 1)
            hotel_total = hotel_rate * rooms
            food_total = food_rate * members
            transport_total = transport_rate * legs * members
            tickets_total = ticket_total * members

            per_person_day = (hotel_total + food_total + transport_total + tickets_total) / members
            capped = min(per_person_day, _MAX_DAILY_PER_PERSON)
            day_total = capped * members

            items = [
                CostLineItem(label=f"Hotel ({hotel_rate:.0f} x {rooms} room(s))", amount=round(hotel_total, 2)),
                CostLineItem(label=f"Food ({food_rate:.0f} x {members} people)", amount=round(food_total, 2)),
                CostLineItem(
                    label=f"Local transport ({legs} leg(s) x {members} people)",
                    amount=round(transport_total, 2),
                ),
                CostLineItem(
                    label=f"Entry tickets ({place_count} place(s) x {members} people)", amount=round(tickets_total, 2)
                ),
            ]
            steps = [
                f"Hotel: {hotel_rate:.0f} x {rooms} room(s) = {hotel_total:.0f}",
                f"Food: {food_rate:.0f} x {members} people = {food_total:.0f}",
                f"Local transport: {transport_rate:.0f} x {legs} leg(s) x {members} people = {transport_total:.0f}",
                f"Entry tickets: {ticket_total:.0f} x {members} people = {tickets_total:.0f}",
                f"Day total: {day_total:.0f} ({per_person_day:.0f} per person)"
                + (" capped at 8000 per person" if capped < per_person_day else ""),
            ]
            daily.append(
                DailyCost(
                    day=day_num,
                    items=items,
                    subtotal=round(day_total, 2),
                    steps=steps,
                )
            )

        grand_total = round(sum(d.subtotal or 0.0 for d in daily), 2)
        per_person_total = round(grand_total / members, 2) if members else 0.0
        overall = OverallCost(
            per_person_total=per_person_total,
            members=members,
            grand_total=grand_total,
            steps=[
                f"Hotel: {hotel_rate:.0f} x {rooms} room(s) x {len(daily)} night(s)",
                f"Food: {food_rate:.0f} x {members} people x {len(daily)} day(s)",
                f"Local transport: {transport_rate:.0f} per leg",
                "Entry tickets estimated per place type (local 100 / popular 300 / major 600)",
                f"Grand total ({members} person(s)): {grand_total:.0f}",
                f"Per person: {per_person_total:.0f}",
            ],
        )

        logger.info("estimate done daily_count={} grand_total={}", len(daily), grand_total)
        return CostEstimate(daily=daily, overall=overall)
