"""Timing critique agent.

Checks if daily schedules are feasible within the daily hour budget.
Pure arithmetic - no LLM needed.
"""

from __future__ import annotations

import math

from loguru import logger

from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.config.settings import get_settings


def _timing_settings():
    s = get_settings()
    return s.sequencing_avg_visit_hrs, s.sequencing_daily_hour_budget


async def critique_timing(state: TripState) -> TripState:
    """Check each day total hours against daily budget."""
    default_avg_visit_hrs, default_daily_hour_budget = _timing_settings()
    skeleton = state.get("day_skeleton", [])
    meta = state.get("trip_meta", {})
    daily_hour_budget = float(meta.get("daily_hour_budget", default_daily_hour_budget))

    critiques = list(state.get("critiques", []))

    for day in skeleton:
        day_num = day.get("day", "?")
        pois = day.get("pois", [])
        total_hours = 0.0
        for poi in pois:
            hrs = float(poi.get("avg_visit_hrs", default_avg_visit_hrs) or default_avg_visit_hrs)
            total_hours += hrs

        if len(pois) > 1:
            total_hours += (len(pois) - 1) * 0.25

        if total_hours > daily_hour_budget:
            excess = total_hours - daily_hour_budget
            drops = math.ceil(excess / default_avg_visit_hrs)
            msg = f"Day {day_num} has {total_hours:.1f}h of activities (budget {daily_hour_budget:.1f}h, excess {excess:.1f}h). Consider splitting across days or dropping {drops} stop(s)."
            critiques.append(msg)
            logger.info("Timing critique: " + msg)

    if not critiques:
        logger.info(f"Timing critique: all days fit within {daily_hour_budget:.1f}h budget")

    return {**state, "critiques": critiques}
