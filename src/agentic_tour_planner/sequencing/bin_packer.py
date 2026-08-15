"""Deterministic day-by-day sequencing of POIs.

Distributes POIs across the requested number of days, packing multiple
POIs into each day until the daily hour budget is exceeded.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from agentic_tour_planner.config.settings import get_settings


def _sequencing_settings() -> tuple[float, float]:
    s = get_settings()
    return s.sequencing_avg_visit_hrs, s.sequencing_daily_hour_budget


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


def _get_visit_hrs(poi: dict[str, Any]) -> float:
    """Get visit hours for a POI, defaulting to DEFAULT_AVG_VISIT_HRS if missing."""
    default_avg_visit_hrs, _ = _sequencing_settings()
    val = poi.get("avg_visit_hrs", default_avg_visit_hrs)
    if val is None:
        return default_avg_visit_hrs
    try:
        return float(val)
    except (ValueError, TypeError):
        return default_avg_visit_hrs


def sequence(
    pois: list[dict[str, Any]],
    duration_days: int,
    daily_hour_budget: float | None = None,
) -> list[dict[str, Any]]:
    """Deterministic day-by-day sequencing.

    Distributes POIs across the requested number of days. Places multiple
    POIs per day when they fit within the daily hour budget.

    Args:
        pois: List of POI dicts (must have 'base_page' and optionally 'avg_visit_hrs').
        duration_days: Number of days available.
        daily_hour_budget: Max hours of activities per day.

    Returns:
        List of day dicts: [{"day": 1, "city": "Gangtok", "pois": [...]}, ...]
    """
    if daily_hour_budget is None:
        _, daily_hour_budget = _sequencing_settings()
    if not pois or duration_days <= 0:
        return []

    _, daily_hour_budget = _sequencing_settings()

    groups = _group_by_city(pois)
    ordered_cities = _order_city_groups(groups)

    # Flatten POIs in city order (largest cluster first)
    ordered_pois: list[dict[str, Any]] = []
    for city in ordered_cities:
        ordered_pois.extend(groups[city])

    if not ordered_pois:
        return []

    # Distribute POIs across days: fill each day until budget exceeded, then next day
    days: list[dict[str, Any]] = []
    current_day = 1
    current_pois: list[dict[str, Any]] = []
    current_hours = 0.0

    for poi in ordered_pois:
        if current_day > duration_days:
            # All days started, add to the day with least hours
            min_idx = min(range(len(days)), key=lambda i: sum(_get_visit_hrs(p) for p in days[i]["pois"]))
            days[min_idx]["pois"].append(poi)
            continue

        visit_hrs = _get_visit_hrs(poi)

        # If adding this POI would exceed budget and day already has POIs, move to next day
        if current_pois and current_hours + visit_hrs > daily_hour_budget:
            days.append({"day": current_day, "city": current_pois[0].get("base_page", "Unknown"), "pois": current_pois})
            current_day += 1
            current_pois = []
            current_hours = 0.0

        current_pois.append(poi)
        current_hours += visit_hrs

    # Don't forget the last day
    if current_pois and current_day <= duration_days:
        days.append({"day": current_day, "city": current_pois[0].get("base_page", "Unknown"), "pois": current_pois})

    # Renumber days to be sequential
    for i, day in enumerate(days):
        day["day"] = i + 1

    logger.info(f"Sequenced {len(pois)} POIs into {len(days)} days")
    return days
