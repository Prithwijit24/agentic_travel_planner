"""Cost agent - LLM-classified cost estimation.

Uses one LLM call to classify each cost line as per_person/per_room/flat,
then applies arithmetic. The LLM provides reasoning; prices come from data.
"""

from __future__ import annotations

from loguru import logger

from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.llm.provider import LLMProvider


def _cost_prompt_hints():
    s = get_settings()
    return {
        "hotel_budget": s.cost_hotel_prompt_budget,
        "hotel_midrange": s.cost_hotel_prompt_midrange,
        "hotel_luxury": s.cost_hotel_prompt_luxury,
        "food_budget": s.cost_food_prompt_budget,
        "food_midrange": s.cost_food_prompt_midrange,
        "food_luxury": s.cost_food_prompt_luxury,
        "transport": s.cost_transport_prompt,
    }


async def estimate_cost(state: TripState) -> TripState:
    """Estimate costs using LLM classification + arithmetic."""
    skeleton = state.get("day_skeleton", [])
    meta = state.get("trip_meta", {})
    travelers = int(meta.get("travelers", 1))
    budget_tier = meta.get("budget_tier", "midrange")

    if not skeleton:
        return {**state, "cost_summary": {"daily_costs": [], "grand_total": 0, "per_person_total": 0}}

    prompt_parts = [
        "Destination: " + str(meta.get("destination", "Unknown")),
        "Travelers: " + str(travelers),
        "Budget tier: " + str(budget_tier),
        "",
        "Day-by-day itinerary:",
    ]

    for day in skeleton:
        prompt_parts.append("")
        prompt_parts.append("Day " + str(day["day"]) + " (" + str(day.get("city", "Unknown")) + "):")
        for poi in day.get("pois", []):
            price = poi.get("price", "unknown")
            prompt_parts.append("  - " + str(poi.get("name", "?")) + " (price: " + str(price) + ")")

    prompt_parts.append("")
    hints = _cost_prompt_hints()
    prompt_parts.append(
        "Hotel estimates: budget={}, midrange={}, luxury={}".format(
            hints["hotel_budget"], hints["hotel_midrange"], hints["hotel_luxury"]
        )
    )
    prompt_parts.append(
        "Food estimates: budget={}, midrange={}, luxury={}".format(
            hints["food_budget"], hints["food_midrange"], hints["food_luxury"]
        )
    )
    prompt_parts.append("Assume double occupancy for hotels. Estimate cab/transport at {}.".format(hints["transport"]))

    prompt = "\n".join(prompt_parts)

    try:
        provider = LLMProvider()
        result = await provider.complete_json(prompt, system_prompt=get_settings().COST_SYSTEM_PROMPT)
        result.setdefault("currency", "INR")
        result["travelers"] = travelers
        result["budget_tier"] = budget_tier
        logger.info(
            "Cost estimated: {} {} for {} travelers".format(
                result.get("grand_total", 0), result.get("currency", "INR"), travelers
            )
        )
        return {**state, "cost_summary": result}
    except Exception as e:
        logger.warning(f"Cost agent failed: {e}")
        return {**state, "cost_summary": {"daily_costs": [], "grand_total": 0, "per_person_total": 0, "error": str(e)}}
