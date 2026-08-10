"""Planner agent - resolves critiques with one LLM call.

Takes accumulated critiques, asks the LLM for a specific revision instruction
in structured JSON, and applies the edit in code (does not trust the LLM to
rewrite the whole skeleton).
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.llm.provider import LLMProvider

REVISION_SYSTEM_PROMPT = (
    "You are a trip revision planner. Given a day-by-day itinerary skeleton and "
    "a list of critiques, propose ONE specific edit to address the issues.\n"
    "Return strict JSON only with one of these actions:\n"
    '  {"action": "drop_poi", "poi_id": "<poi_id>", "day": <day_number>}\n'
    '  {"action": "move_poi", "poi_id": "<poi_id", "from_day": <day>, "to_day": <day>}\n'
    '  {"action": "swap_poi", "drop_poi_id": "<id>", "add_poi_id": "<id>", "day": <day>}\n'
    "Choose the single most impactful edit. Do not rewrite the entire itinerary."
)


async def resolve_critiques(state: TripState) -> TripState:
    """Resolve critiques with one LLM call + code-applied edit."""
    critiques = state.get("critiques", [])
    skeleton = state.get("day_skeleton", [])

    if not critiques:
        return {**state, "revision_count": state.get("revision_count", 0)}

    # Build prompt
    prompt_parts = ["Critiques to address:"]
    for i, c in enumerate(critiques, 1):
        prompt_parts.append(str(i) + ". " + str(c))

    prompt_parts.append("")
    prompt_parts.append("Current itinerary skeleton:")
    for day in skeleton:
        prompt_parts.append("Day " + str(day.get("day", "?")) + ":")
        for poi in day.get("pois", []):
            prompt_parts.append("  - " + str(poi.get("poi_id", "?") + ": " + str(poi.get("name", "?"))))

    prompt = "\n".join(prompt_parts)

    try:
        provider = LLMProvider()
        result = await provider.complete_json(prompt, system_prompt=REVISION_SYSTEM_PROMPT)
        action = result.get("action", "")
        logger.info("Planner agent proposed: {}".format(action))

        # Apply the edit in code
        new_skeleton = _apply_edit(skeleton, result)
        revision_count = state.get("revision_count", 0) + 1

        return {**state, "day_skeleton": new_skeleton, "revision_count": revision_count}
    except Exception as e:
        logger.warning("Planner agent failed: {}".format(e))
        return {**state, "revision_count": state.get("revision_count", 0) + 1}


def _apply_edit(skeleton: list[dict[str, Any]], instruction: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply a structured edit instruction to the skeleton."""
    action = instruction.get("action", "")
    poi_id = instruction.get("poi_id", instruction.get("drop_poi_id", ""))
    day_num = instruction.get("day")

    new_skeleton = [dict(day) for day in skeleton]

    if action in ("drop_poi", "swap_poi"):
        for day in new_skeleton:
            if day.get("day") == day_num:
                day["pois"] = [p for p in day.get("pois", []) if p.get("poi_id") != poi_id]
                break

    elif action == "move_poi":
        from_day = instruction.get("from_day")
        to_day = instruction.get("to_day")
        moved_poi = None
        for day in new_skeleton:
            if day.get("day") == from_day:
                for p in day.get("pois", []):
                    if p.get("poi_id") == poi_id:
                        moved_poi = p
                        break
                if moved_poi:
                    day["pois"] = [p for p in day["pois"] if p.get("poi_id") != poi_id]
                    break
        if moved_poi:
            for day in new_skeleton:
                if day.get("day") == to_day:
                    day.setdefault("pois", []).append(moved_poi)
                    break

    return new_skeleton
