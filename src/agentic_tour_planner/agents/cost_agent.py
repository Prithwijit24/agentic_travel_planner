"""Cost agent - LLM-classified cost estimation.

Uses one LLM call to classify each cost line as per_person/per_room/flat,
then applies arithmetic. The LLM provides reasoning; prices come from data.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.llm.provider import LLMProvider

COST_SYSTEM_PROMPT = (
    "You are a travel cost classifier. Given a day-by-day itinerary skeleton "
    "with POI prices and trip metadata, classify each cost line item as one of:\n"
    "- per_person: entries, meals, tickets, activities (multiply by number of travelers)\n"
    "- per_room: hotels, lodging (multiply by rooms needed = ceil(travelers / occupancy))\n"
    "- flat: cab hire, vehicle rental, guide fees (count once per use, not per person)\n"
    "Return strict JSON only with keys: daily_costs (list of day objects with items, "
    "day_total_per_person, day_total_all_travelers), grand_total, per_person_total, "
    "currency, notes. Use the POI price field when available. For unknown amounts, "
    "estimate reasonably for the destination and budget_tier. Never invent POIs."
)


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
    prompt_parts.append("Hotel estimates: budget=Rs800-1500/room, midrange=Rs2500-6000/room, luxury=Rs8000-25000/room")
    prompt_parts.append("Food estimates: budget=Rs300-600/person/day, midrange=Rs800-2000/person/day, luxury=Rs2500-8000/person/day")
    prompt_parts.append("Assume double occupancy for hotels. Estimate cab/transport at Rs300-800 per trip.")

    prompt = "\n".join(prompt_parts)

    try:
        provider = LLMProvider()
        result = await provider.complete_json(prompt, system_prompt=COST_SYSTEM_PROMPT)
        result.setdefault("currency", "INR")
        result["travelers"] = travelers
        result["budget_tier"] = budget_tier
        logger.info("Cost estimated: {} {} for {} travelers".format(
            result.get("grand_total", 0), result.get("currency", "INR"), travelers))
        return {**state, "cost_summary": result}
    except Exception as e:
        logger.warning("Cost agent failed: {}".format(e))
        return {**state, "cost_summary": {"daily_costs": [], "grand_total": 0, "per_person_total": 0, "error": str(e)}}
