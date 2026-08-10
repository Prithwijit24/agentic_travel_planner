"""Budget critique agent.

Checks if the cost summary exceeds per-person/day thresholds for the budget_tier.
Pure arithmetic - no LLM needed for the decision.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from agentic_tour_planner.agents.state import TripState

# Per-person daily thresholds by budget tier (in INR)
BUDGET_THRESHOLDS = {
    "budget": 3000,
    "midrange": 8000,
    "luxury": 25000,
}


async def critique_budget(state: TripState) -> TripState:
    """Check if daily costs exceed budget threshold."""
    cost_summary = state.get("cost_summary", {})
    meta = state.get("trip_meta", {})
    budget_tier = meta.get("budget_tier", "midrange")
    travelers = int(meta.get("travelers", 1))
    threshold = BUDGET_THRESHOLDS.get(budget_tier, 8000)

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
            msg = "Day {} exceeds {} budget: Rs {:.0f}/person (threshold Rs {:.0f}, excess Rs {:.0f}). Consider dropping a paid attraction or switching to a cheaper hotel.".format(
                day, budget_tier, per_person, threshold, excess)
            critiques.append(msg)
            logger.info("Budget critique: " + msg)

    if not critiques:
        logger.info("Budget critique: all days within {} threshold (Rs {}/person/day)".format(budget_tier, threshold))

    return {**state, "critiques": critiques}
