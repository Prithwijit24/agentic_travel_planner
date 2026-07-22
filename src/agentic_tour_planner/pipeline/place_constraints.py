from __future__ import annotations

import re

from agentic_tour_planner.domain.models import DayPlan, PlanningRequest, SpotDetail, parse_place_range


def enforce_minimum_daily_spots(
    request: PlanningRequest,
    itinerary: list[DayPlan],
) -> list[DayPlan]:
    """Guarantee the user-requested minimum count in each regular day's visible place list."""
    min_places, _ = parse_place_range(
        request.places_per_day,
        default=(request.max_attractions_per_day, request.max_attractions_per_day),
    )
    min_places = max(1, min(min_places, 8))
    for day in itinerary:
        existing = {spot.name.strip().lower() for spot in day.spots if spot.name}
        candidates = extract_activity_place_names(day, request.destination)
        for name in candidates:
            if len(day.spots) >= min_places:
                break
            key = name.strip().lower()
            if not key or key in existing:
                continue
            day.spots.append(
                SpotDetail(
                    name=name,
                    description="Optional place added to satisfy the requested places-per-day minimum.",
                    image_query=name,
                )
            )
            existing.add(key)
        while len(day.spots) < min_places:
            idx = len(day.spots) + 1
            name = f"{request.destination} optional place {idx}"
            day.spots.append(
                SpotDetail(
                    name=name,
                    description="Optional placeholder requiring local verification; added because the planner returned too few places.",
                    image_query=f"{request.destination} attraction",
                )
            )
    return itinerary


def extract_activity_place_names(day: DayPlan, destination: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    stop_words = {
        "Morning",
        "Late Morning",
        "Midday",
        "Afternoon",
        "Late Afternoon",
        "Evening",
        "Breakfast",
        "Lunch",
        "Dinner",
        "Visit",
        "Explore",
        "Walk",
        "Transfer",
        "Hotel",
    }
    pattern = re.compile(r"\b([A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*){0,5})")
    for activity in [*day.morning, *day.afternoon, *day.evening]:
        for match in pattern.findall(activity):
            name = match.strip(" :-–—")
            if name in stop_words or name == destination:
                continue
            key = name.lower()
            if key not in seen:
                seen.add(key)
                names.append(name)
    return names
