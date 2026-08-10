"""Deterministic day-by-day sequencing of POIs.

Groups POIs by city, orders cities, and greedily packs into days
respecting a daily hour budget.
"""

from __future__ import annotations

import math
from typing import Any

from loguru import logger

DEFAULT_AVG_VISIT_HRS = 1.5
DEFAULT_DAILY_HOUR_BUDGET = 8.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _group_by_city(pois: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group POIs by their base_page (city)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for poi in pois:
        city = poi.get("base_page", "Unknown")
        groups.setdefault(city, []).append(poi)
    return groups


def _order_city_groups(groups: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Order city groups by size (largest first) as a simple heuristic.

    TODO: Improve with transit data or geographic proximity once available.
    """
    return sorted(groups.keys(), key=lambda city: len(groups[city]), reverse=True)


def sequence(
    pois: list[dict[str, Any]],
    duration_days: int,
    daily_hour_budget: float = DEFAULT_DAILY_HOUR_BUDGET,
) -> list[dict[str, Any]]:
    """Deterministic day-by-day sequencing.

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

    # Greedy bin-packing into days
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

        # Start a new day if budget exceeded or city changes significantly
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

    # Don't forget the last day
    if current_pois and current_day <= duration_days:
        days.append({"day": current_day, "city": current_city, "pois": current_pois})

    logger.info(f"Sequenced {len(pois)} POIs into {len(days)} days")
    return days
