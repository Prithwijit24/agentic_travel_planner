from __future__ import annotations

from dataclasses import dataclass

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import DayPlan, PlanningRequest


def _constraints():
    s = get_settings()
    return s.constraints_far_apart_km, s.constraints_far_apart_min, s.constraints_daily_travel_budget_min


@dataclass
class TravelLeg:
    origin: str
    destination: str
    distance_km: float
    duration_minutes: float


async def lookup_travel_leg(origin: str, destination: str, _request: PlanningRequest) -> TravelLeg:
    return TravelLeg(
        origin=origin,
        destination=destination,
        distance_km=0.0,
        duration_minutes=0.0,
    )


async def annotate_travel_constraints(request: PlanningRequest, itinerary: list[DayPlan]) -> list[DayPlan]:
    far_apart_km, far_apart_min, daily_travel_budget_min = _constraints()
    for day in itinerary:
        spots = day.spots
        total_duration = 0.0
        has_long_leg = False

        for i in range(len(spots) - 1):
            leg = await lookup_travel_leg(spots[i].name, spots[i + 1].name, request)
            total_duration += leg.duration_minutes

            if leg.distance_km > far_apart_km or leg.duration_minutes > far_apart_min:
                has_long_leg = True
                msg = (
                    f"{spots[i].name} and {spots[i + 1].name} are {leg.distance_km:.0f} km apart "
                    f"({leg.duration_minutes:.0f} min) — these spots are far apart; "
                    f"consider adjusting your route."
                )
                day.logistics.append(msg)

        if has_long_leg:
            day.rationale = (
                f"There is significant travel time between some spots on day {day.day}. "
                f"Consider grouping nearby attractions together."
            )

        if total_duration > daily_travel_budget_min:
            hours = int(total_duration // 60)
            minutes = int(total_duration % 60)
            parts = []
            if hours > 0:
                parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
            if minutes > 0:
                parts.append(f"{minutes} min")
            time_str = " ".join(parts)
            day.logistics.append(
                f"You have {total_duration:.0f} min of travel ({time_str}) on day {day.day} — "
                f"this exceeds the daily travel budget of {daily_travel_budget_min:.0f} min "
                f"({int(daily_travel_budget_min // 60)} hours). Consider reducing the number of stops."
            )

    return itinerary
