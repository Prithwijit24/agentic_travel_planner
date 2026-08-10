"""Timing critique agent.

Checks if daily schedules are feasible within the daily hour budget.
Pure arithmetic - no LLM needed.
"""

from __future__ import annotations

import math

from loguru import logger

from agentic_tour_planner.agents.state import TripState

DEFAULT_AVG_VISIT_HRS = 1.5
DEFAULT_DAILY_HOUR_BUDGET = 8.0


async def critique_timing(state: TripState) -> TripState:
    """Check each day total hours against daily budget."""
    skeleton = state.get("day_skeleton", [])
    meta = state.get("trip_meta", {})
    daily_hour_budget = float(meta.get("daily_hour_budget", DEFAULT_DAILY_HOUR_BUDGET))

    critiques = list(state.get("critiques", []))

    for day in skeleton:
        day_num = day.get("day", "?")
        pois = day.get("pois", [])
        total_hours = 0.0
        for poi in pois:
            hrs = float(poi.get("avg_visit_hrs", DEFAULT_AVG_VISIT_HRS) or DEFAULT_AVG_VISIT_HRS)
            total_hours += hrs

        # Add estimated inter-POI travel time (15 min between POIs in same city)
        if len(pois) > 1:
            total_hours += (len(pois) - 1) * 0.25

        if total_hours > daily_hour_budget:
            excess = total_hours - daily_hour_budget
            msg = "Day {} has {:.1f}h of activities (budget {:.1f}h, excess {:.1f}h). Consider splitting across days or dropping {} stop(s).".format(
                day_num, total_hours, daily_hour_budget, math.ceil(excess / DEFAULT_AVG_VISIT_HRS))
            critiques.append(msg)
            logger.info("Timing critique: " + msg)

    if not critiques:
        logger.info("Timing critique: all days fit within {:.1f}h budget".format(daily_hour_budget))

    return {**state, "critiques": critiques}
