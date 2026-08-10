"""Single-pass LLM narration.

Replaces the old 3-pass generation with one LLM call.
Includes retry + template fallback.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from agentic_tour_planner.llm.provider import LLMProvider

NARRATION_SYSTEM_PROMPT = (
    "You are a travel itinerary narrator. Given a fixed day-by-day skeleton with "
    "POI names, descriptions, costs, weather, and any known limitations, write "
    "a compelling travel overview and per-day narrative.\n"
    "RULES:\n"
    "- Do NOT reorder the days or POIs.\n"
    "- Do NOT invent POIs, facts, or attractions not in the skeleton.\n"
    "- Use the exact POI names from the skeleton.\n"
    "- Mention costs only if they are provided in the cost summary.\n"
    "- Keep each day narrative to 2-3 paragraphs.\n"
    "Return strict JSON only:\n"
    '{\n'
    '  "overview": "string (2-3 sentences about the trip)",\n'
    '  "days": [\n'
    '    {"day": 1, "narrative": "string", "tip": "string (one practical tip for the day)"}\n'
    '  ],\n'
    '  "general_tips": ["string"]\n'
    '}\n'
)


async def narrate_trip(
    trip_meta: dict[str, Any],
    day_skeleton: list[dict[str, Any]],
    cost_summary: dict[str, Any],
    weather: dict[str, Any] | None = None,
    known_limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Generate narration in a single LLM call.

    Retries once on JSON parse failure, then falls back to a template.
    """
    weather = weather or {}
    known_limitations = known_limitations or []

    prompt = _build_prompt(trip_meta, day_skeleton, cost_summary, weather, known_limitations)

    try:
        provider = LLMProvider()
        result = await provider.complete_json(prompt, system_prompt=NARRATION_SYSTEM_PROMPT)

        # Validate shape
        if "overview" in result and "days" in result:
            return result

        # Retry with stricter prompt
        logger.warning("Narration shape invalid, retrying with stricter prompt")
        retry_prompt = prompt + "\n\nIMPORTANT: Return ONLY valid JSON with keys: overview, days (list of objects with day/narrative/tip), general_tips."
        result = await provider.complete_json(retry_prompt, system_prompt=NARRATION_SYSTEM_PROMPT)
        if "overview" in result and "days" in result:
            return result
    except Exception as e:
        logger.warning("Narration LLM call failed: {}".format(e))

    # Template fallback
    return _template_fallback(trip_meta, day_skeleton, known_limitations)


def _build_prompt(
    trip_meta: dict[str, Any],
    day_skeleton: list[dict[str, Any]],
    cost_summary: dict[str, Any],
    weather: dict[str, Any],
    known_limitations: list[str],
) -> str:
    """Build the narration prompt from structured data."""
    parts = []
    parts.append("Destination: " + str(trip_meta.get("destination", "Unknown")))
    parts.append("Duration: " + str(trip_meta.get("duration_days", len(day_skeleton))) + " days")
    parts.append("Travelers: " + str(trip_meta.get("travelers", 1)))
    parts.append("Budget tier: " + str(trip_meta.get("budget_tier", "midrange")))

    if weather:
        parts.append("Weather: " + str(weather.get("summary", "N/A")))

    if cost_summary:
        parts.append("Total cost: Rs {} (Rs {} per person)".format(
            cost_summary.get("grand_total", "N/A"),
            cost_summary.get("per_person_total", "N/A")))

    if known_limitations:
        parts.append("")
        parts.append("Known limitations (mention briefly):")
        for lim in known_limitations:
            parts.append("  - " + str(lim))

    parts.append("")
    parts.append("Itinerary skeleton:")
    for day in day_skeleton:
        parts.append("")
        parts.append("Day " + str(day.get("day", "?")) + " - " + str(day.get("city", "Unknown")) + ":")
        for poi in day.get("pois", []):
            desc = poi.get("long_description", "")
            price = poi.get("price", "")
            line = "  - " + str(poi.get("name", "?"))
            if desc:
                line += ": " + str(desc)[:100]
            if price:
                line += " (Price: " + str(price) + ")"
            parts.append(line)

    return "\n".join(parts)


def _template_fallback(
    trip_meta: dict[str, Any],
    day_skeleton: list[dict[str, Any]],
    known_limitations: list[str],
) -> dict[str, Any]:
    """Build a plain-text template when LLM fails."""
    dest = trip_meta.get("destination", "your destination")
    overview = "A wonderful {}-day trip to {}. Enjoy the sights, sounds, and flavors of this beautiful destination.".format(
        len(day_skeleton), dest)

    days = []
    for day in day_skeleton:
        poi_names = [p.get("name", "?") for p in day.get("pois", [])]
        narrative = "Day {} in {}. Visit {}.".format(
            day.get("day", "?"),
            day.get("city", "the area"),
            ", ".join(poi_names) if poi_names else "local attractions")
        days.append({"day": day.get("day", 0), "narrative": narrative, "tip": "Plan ahead for a smooth day."})

    tips = ["Carry cash for small vendors.", "Check opening hours before visiting."]
    if known_limitations:
        tips.extend(known_limitations[:2])

    return {"overview": overview, "days": days, "general_tips": tips}
