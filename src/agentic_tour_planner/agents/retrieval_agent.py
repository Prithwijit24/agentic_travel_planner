"""RAG query reformulation agent.

Reformulates interest tags into 3-4 search phrases for broader retrieval.
Falls back to the original tags if LLM is unavailable.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.llm.provider import LLMProvider

REFORMULATE_SYSTEM_PROMPT = (
    "You are a travel search query reformulator. Given a destination and a list "
    "of interest tags, generate 3-4 diverse search phrases that cover different "
    "aspects of the interests.\n"
    "For example, for interests ['monasteries', 'nature'] in Sikkim, you might generate:\n"
    "  - 'Buddhist monasteries heritage Sikkim'\n"
    "  - 'quiet mountain valleys lakes nature'\n"
    "  - 'trekking trails scenic viewpoints'\n"
    "  - 'local culture traditional festivals'\n"
    "Return strict JSON only: {"phrases": ["phrase1", "phrase2", ...]}"
)


async def reformulate_and_retrieve(
    destination: str,
    interest_tags: list[str],
    retrieve_fn,
) -> list[dict[str, Any]]:
    """Reformulate interest tags and retrieve using multiple phrases.

    Args:
        destination: The destination name.
        interest_tags: Original interest tags.
        retrieve_fn: Async callable that takes (destination, tags) and returns POIs.

    Returns:
        Merged, deduplicated list of POI records.
    """
    settings = get_settings()
    if not getattr(settings, "use_rag_reformulation", False):
        return await retrieve_fn(destination, interest_tags)

    # Try LLM reformulation
    try:
        provider = LLMProvider()
        prompt = "Destination: " + str(destination) + "\nInterests: " + ", ".join(interest_tags)
        result = await provider.complete_json(prompt, system_prompt=REFORMULATE_SYSTEM_PROMPT)
        phrases = result.get("phrases", [])
        if not phrases:
            raise ValueError("No phrases returned")
    except Exception as e:
        logger.warning("Reformulation failed, using original tags: {}".format(e))
        return await retrieve_fn(destination, interest_tags)

    # Retrieve using each phrase
    seen_ids = set()
    all_pois = []

    for phrase in phrases:
        phrase_tags = [phrase]  # Use phrase as a single tag query
        try:
            pois = await retrieve_fn(destination, phrase_tags)
            for poi in pois:
                poi_id = poi.get("poi_id")
                if poi_id and poi_id not in seen_ids:
                    seen_ids.add(poi_id)
                    all_pois.append(poi)
        except Exception as e:
            logger.warning("Retrieval for phrase '{}' failed: {}".format(phrase, e))

    # If reformulation returned nothing useful, fall back to original
    if not all_pois:
        logger.info("Reformulation returned no results, falling back to original tags")
        return await retrieve_fn(destination, interest_tags)

    logger.info("Reformulation: {} phrases -> {} unique POIs".format(len(phrases), len(all_pois)))
    return all_pois
