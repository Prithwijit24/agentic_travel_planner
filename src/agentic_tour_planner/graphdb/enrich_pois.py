"""LLM enrichment of raw POIs.

Reads raw pois.jsonl (from parse_dump.py) and uses oraclellm to generate,
for each place, a rich ~200-word description and an exhaustive set of tags.

Output: enriched_pois.jsonl — one JSON object per line with all original
fields PLUS:
  - rich_description: ~200 words of pure prose (description + history + facts)
  - tags: exhaustive flat list of theme/activity/feature tags

Idempotent: skips POIs already present in the enriched file (matched by poi_id),
so re-runs only process new entries.

Run:
    python -m agentic_tour_planner.graphdb.enrich_pois [data-dir]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from loguru import logger

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.llm.provider import LLMProvider


def _build_prompt(poi: dict) -> str:
    return str(
        get_settings().ENRICHMENT_USER_PROMPT.format(
            name=poi.get("name", ""),
            category=poi.get("category", ""),
            region=poi.get("base_page", ""),
            destination=poi.get("base_page", ""),
            current_description=poi.get("long_description", ""),
            hours=poi.get("hours", "unknown"),
            price=poi.get("price", "unknown"),
        )
    )


async def _enrich_one(provider: LLMProvider, poi: dict) -> dict | None:
    prompt = _build_prompt(poi)
    try:
        result = await provider.complete_json(prompt, system_prompt=get_settings().ENRICHMENT_SYSTEM_PROMPT)
    except Exception as e:
        logger.warning("LLM enrichment failed for {}: {}".format(poi.get("poi_id", poi.get("name", "?")), e))
        return None

    rich_description = result.get("rich_description", "").strip()
    tags = result.get("tags", [])

    if not rich_description:
        logger.warning("Empty description for {}".format(poi.get("poi_id", "?")))
        return None

    tags = [str(t).strip().lower() for t in tags if str(t).strip()]

    enriched = dict(poi)
    enriched["rich_description"] = rich_description
    enriched["tags"] = tags
    return enriched


async def enrich_pois(data_dir: str | None = None, delay_seconds: float = 0.5) -> tuple[int, int]:
    """Enrich all POIs in pois.jsonl with LLM-generated content.

    Returns (enriched_count, skipped_count).
    """
    data_path = Path(data_dir) if data_dir else Path()
    pois_file = data_path / "pois.jsonl"
    out_file = data_path / "enriched_pois.jsonl"

    if not pois_file.exists():
        raise FileNotFoundError(f"pois.jsonl not found in {data_path}")

    raw_pois = [json.loads(line) for line in pois_file.open(encoding="utf-8") if line.strip()]

    # Load existing enriched POIs for idempotency
    existing: dict[str, dict] = {}
    if out_file.exists():
        for line in out_file.open(encoding="utf-8"):
            if line.strip():
                d = json.loads(line)
                existing[d["poi_id"]] = d

    provider = LLMProvider()
    enriched_count = 0
    skipped_count = 0

    with out_file.open("w", encoding="utf-8") as f:
        # Write existing entries first
        for d in existing.values():
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

        for poi in raw_pois:
            poi_id = poi.get("poi_id", "")
            if poi_id in existing:
                skipped_count += 1
                continue

            logger.info(f"Enriching: {poi_id}")
            enriched = await _enrich_one(provider, poi)
            if enriched:
                f.write(json.dumps(enriched, ensure_ascii=False) + "\n")
                f.flush()
                enriched_count += 1
                logger.info(
                    "  -> {} words, {} tags".format(
                        len(enriched["rich_description"].split()),
                        len(enriched["tags"]),
                    )
                )
            else:
                skipped_count += 1

            if delay_seconds > 0:
                time.sleep(delay_seconds)

    logger.info(f"Enrichment complete: {enriched_count} enriched, {skipped_count} skipped/failed")
    return enriched_count, skipped_count


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    enriched, skipped = asyncio.run(enrich_pois(data_dir))
    print(f"Done. Enriched: {enriched}, Skipped: {skipped}")
