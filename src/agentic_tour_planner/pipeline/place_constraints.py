from __future__ import annotations

import re

from agentic_tour_planner.domain.models import DayPlan, PlanningRequest, SpotDetail, parse_place_range


def enforce_minimum_daily_spots(
    request: PlanningRequest,
    itinerary: list[DayPlan],
) -> list[DayPlan]:
    """Guarantee the user-requested minimum count in each regular day's visible place list.

    Only real, confidently-named places are added as backfill. Unverifiable time/phase
    labels and generic placeholders are never injected as spots.
    """
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
                    description="Popular attraction worth including in your day.",
                    best_time="Check local timings before visiting.",
                    image_query=name,
                )
            )
            existing.add(key)
    return itinerary


def extract_activity_place_names(day: DayPlan, destination: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    # Time-of-day / logistics / non-place words that are NOT real attractions.
    drop_words = {
        "Morning",
        "Late Morning",
        "Midday",
        "Afternoon",
        "Late Afternoon",
        "Evening",
        "Early",
        "Late",
        "Noon",
        "Dawn",
        "Dusk",
        "Night",
        "Nightfall",
        "Breakfast",
        "Lunch",
        "Dinner",
        "Brunch",
        "Snack",
        "Tea",
        "Coffee",
        "Visit",
        "Explore",
        "Walk",
        "Drive",
        "Transfer",
        "Travel",
        "Tour",
        "Hotel",
        "Check-in",
        "Check-out",
        "Arrival",
        "Arrive",
        "Departure",
        "Depart",
        "Transit",
        "Return",
        "Free Time",
        "En Route",
        "Rest",
        "Overview",
    }

    # Strong "place" markers: names containing these are kept even if short.
    place_markers = (
        "temple",
        "monastery",
        "church",
        "mosque",
        "palace",
        "fort",
        "museum",
        "gallery",
        "garden",
        "park",
        "lake",
        "ridge",
        "view",
        "viewpoint",
        "point",
        "pass",
        "valley",
        "falls",
        "waterfall",
        "beach",
        "harbour",
        "market",
        "bazaar",
        "bridge",
        "street",
        "square",
        "statue",
        "monument",
        "tower",
        "peak",
        "hill",
        "cave",
        "college",
        "university",
        "station",
        "ghat",
        "island",
        "sanctuary",
        "reserve",
        "national park",
        "trek",
        "trail",
    )

    def _is_place_candidate(name: str) -> bool:
        n_lower = name.lower()
        if not name or len(name) < 3:
            return False
        if name in drop_words or n_lower in drop_words or name == destination:
            return False
        # A time window/constraint fragment ends with a digit or colon pattern.
        if re.search(r"\d", name):
            return False
        # Allow 'Point (Monastery)' style but drop pure '(time)' noise.
        if (":" in name or "(" in name or ")" in name) and len(name) <= 6:
            return False
        # keep names that clearly reference a place type / proper place
        if any(mk in n_lower for mk in place_markers):
            return True
        # otherwise require a multi-word proper noun (to avoid stray words like 'Early')
        return len(name.split()) >= 2 and name[0].isupper()

    pattern = re.compile(r"\b([A-Z][\w'\u2019\u201d.-]*(?:\s+[A-Z][\w'\u201d\u2019.-]*){0,5})")
    for activity in [*day.morning, *day.afternoon, *day.evening]:
        for match in pattern.findall(activity):
            name = match.strip(" :\u2013\u2014()")
            if not name:
                continue
            # Only take the leading run before any time spec like "Morning 6:00-8:30"
            name = re.split(r"\s+(?:Morning|Late Morning|Midday|Afternoon|Late Afternoon|Evening)\b", name, maxsplit=1)[
                0
            ].strip()
            name = name.rstrip(" ,:\u2013\u2014")
            if not _is_place_candidate(name):
                continue
            key = name.lower()
            if key not in seen:
                seen.add(key)
                names.append(name)
    return names
