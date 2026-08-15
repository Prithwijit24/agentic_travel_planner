"""Budget critique agent.

Checks if the cost summary exceeds per-person/day thresholds for the budget_tier.
Pure arithmetic - no LLM needed for the decision.
"""

from __future__ import annotations

from loguru import logger

from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.config.settings import get_settings


def _budget_thresholds():
    s = get_settings()
    return {
        "budget": s.budget_threshold_budget,
        "midrange": s.budget_threshold_midrange,
        "luxury": s.budget_threshold_luxury,
    }


async def critique_budget(state: TripState) -> TripState:
    """Check if daily costs exceed budget threshold."""
    cost_summary = state.get("cost_summary", {})
    meta = state.get("trip_meta", {})
    budget_tier = meta.get("budget_tier", "midrange")
    thresholds = _budget_thresholds()
    threshold = thresholds.get(budget_tier, 8000)

    critiques = list(state.get("critiques", []))
    daily_costs = cost_summary.get("daily_costs", [])

    for day_cost in daily_costs:
        day = day_cost.get("day", "?")
        per_person = day_cost.get("day_total_per_person", 0)
        try:
            per_person = float(per_person)
        except (ValueError, TypeError):
            continue
        if per_person > threshold:
            excess = per_person - threshold
            msg = f"Day {day} exceeds {budget_tier} budget: Rs {per_person:.0f}/person (threshold Rs {threshold:.0f}, excess Rs {excess:.0f}). Consider dropping a paid attraction or switching to a cheaper hotel."
            critiques.append(msg)
            logger.info("Budget critique: " + msg)

    if not critiques:
        logger.info(f"Budget critique: all days within {budget_tier} threshold (Rs {threshold}/person/day)")

    return {**state, "critiques": critiques}
