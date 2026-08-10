"""Deterministic day-by-day sequencing of POIs.

Groups POIs by city, orders cities, and distributes across days
respecting a daily hour budget. Ensures at least N days are created
when N days are requested (unless insufficient POIs).
"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

DEFAULT_AVG_VISIT_HRS = 1.5
DEFAULT_DAILY_HOUR_BUDGET = 8.0


def _group_by_city(pois: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group POIs by their base_page (city)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for poi in pois:
        city = poi.get("base_page", "Unknown")
        groups.setdefault(city, []).append(poi)
    return groups


def _order_city_groups(groups: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Order city groups by size (largest first)."""
    return sorted(groups.keys(), key=lambda city: len(groups[city]), reverse=True)


def sequence(
    pois: list[dict[str, Any]],
    duration_days: int,
    daily_hour_budget: float = DEFAULT_DAILY_HOUR_BUDGET,
) -> list[dict[str, Any]]:
    """Deterministic day-by-day sequencing.

    Distributes POIs across exactly duration_days (when possible),
    respecting the daily hour budget. Creates a round-robin distribution
    across days when all POIs are in the same city.

    Args:
        pois: List of POI dicts (must have 'base_page' and optionally 'avg_visit_hrs').
        duration_days: Number of days available.
        daily_hour_budget: Max hours of activities per day.

    Returns:
        List of day dicts: [{"day": 1, "city": "Gangtok", "pois": [...]}, ...]
    """
    if not pois or duration_days <= 0:
        return []

    groups = _group_by_city(pois)
    ordered_cities = _order_city_groups(groups)

    # Flatten POIs in city order (largest cluster first)
    ordered_pois: list[dict[str, Any]] = []
    for city in ordered_cities:
        ordered_pois.extend(groups[city])

    if not ordered_pois:
        return []

    # If all POIs are in one city, distribute round-robin across days
    if len(ordered_cities) == 1 and len(ordered_pois) > duration_days:
        days: list[list[dict[str, Any]]] = [[] for _ in range(duration_days)]
        day_hours = [0.0] * duration_days
        current_day = 0

        for poi in ordered_pois:
            visit_hrs = float(poi.get("avg_visit_hrs", DEFAULT_AVG_VISIT_HRS) or DEFAULT_AVG_VISIT_HRS)

            # Find the day with the least hours that can fit this POI
            placed = False
            for attempt in range(duration_days):
                idx = (current_day + attempt) % duration_days
                if day_hours[idx] + visit_hrs <= daily_hour_budget:
                    days[idx].append(poi)
                    day_hours[idx] += visit_hrs
                    current_day = (idx + 1) % duration_days
                    placed = True
                    break

            if not placed:
                # All days full, add to the day with least hours
                min_idx = day_hours.index(min(day_hours))
                days[min_idx].append(poi)
                day_hours[min_idx] += visit_hrs

        return [
            {"day": i + 1, "city": ordered_cities[0], "pois": day_pois}
            for i, day_pois in enumerate(days)
            if day_pois  # Only include non-empty days
        ]

    # Multi-city: greedy bin-packing by city group
    days: list[dict[str, Any]] = []
    current_day = 1
    current_city = None
    current_pois: list[dict[str, Any]] = []
    current_hours = 0.0

    for poi in ordered_pois:
        if current_day > duration_days:
            break

        city = poi.get("base_page", "Unknown")
        visit_hrs = float(poi.get("avg_visit_hrs", DEFAULT_AVG_VISIT_HRS) or DEFAULT_AVG_VISIT_HRS)

        if current_pois and (current_hours + visit_hrs > daily_hour_budget or city != current_city):
            days.append({"day": current_day, "city": current_city, "pois": current_pois})
            current_day += 1
            current_pois = []
            current_hours = 0.0

            if current_day > duration_days:
                break

        current_city = city
        current_pois.append(poi)
        current_hours += visit_hrs

    if current_pois and current_day <= duration_days:
        days.append({"day": current_day, "city": current_city, "pois": current_pois})

    # If we have fewer days than requested and enough POIs, split largest day
    while len(days) < duration_days and len(pois) > len(days):
        # Find the day with the most POIs and split it
        largest_idx = max(range(len(days)), key=lambda i: len(days[i]["pois"]))
        largest = days[largest_idx]
        if len(largest["pois"]) < 2:
            break
        mid = len(largest["pois"]) // 2
        day_num = largest["day"]
        # Split into two days
        days[largest_idx] = {"day": day_num, "city": largest["city"], "pois": largest["pois"][:mid]}
        days.insert(largest_idx + 1, {"day": day_num, "city": largest["city"], "pois": largest["pois"][mid:]})

    # Renumber days
    for i, day in enumerate(days):
        day["day"] = i + 1

    logger.info("Sequenced {} POIs into {} days".format(len(pois), len(days)))
    return days
