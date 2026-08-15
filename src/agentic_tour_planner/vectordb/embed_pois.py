"""Embed enriched POI descriptions into ChromaDB.

Reads enriched_pois.jsonl (from enrich_pois.py) and embeds the rich_description
into ChromaDB for vector search. Metadata includes name, category, tags,
region, and coordinates — consistent naming with Neo4j.

Run:
    python -m agentic_tour_planner.vectordb.embed_pois [data-dir]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from loguru import logger

from agentic_tour_planner.vectordb.client import get_vector_db


def embed_pois(data_dir: str | None = None) -> tuple[int, int]:
    """Read enriched_pois.jsonl and embed into ChromaDB.

    Returns (embedded_count, skipped_count).
    """
    data_path = Path(data_dir) if data_dir else Path()
    enriched_file = data_path / "enriched_pois.jsonl"

    if not enriched_file.exists():
        raise FileNotFoundError(f"enriched_pois.jsonl not found in {data_path}. Run enrich_pois first.")

    pois = [json.loads(line) for line in enriched_file.open(encoding="utf-8") if line.strip()]

    ids = []
    documents = []
    metadatas = []
    skipped = 0

    for poi in pois:
        description = poi.get("rich_description", "").strip()
        if not description:
            skipped += 1
            continue

        ids.append(poi["poi_id"])
        documents.append(description)
        metadatas.append(
            {
                "poi_id": poi["poi_id"],
                "name": poi.get("name", ""),
                "category": poi.get("category", ""),
                "tags": ", ".join(poi.get("tags", [])),
                "region": poi.get("base_page", ""),
                "lat": poi.get("lat"),
                "long": poi.get("long"),
            }
        )

    if ids:
        client = get_vector_db()
        col = client.get_collection()
        existing = col.get()["ids"]
        if existing:
            col.delete(ids=existing)
        client.add_pois(ids=ids, documents=documents, metadatas=metadatas)

    logger.info(f"Embedded {len(ids)} POIs, skipped {skipped} (empty descriptions)")
    return len(ids), skipped


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    embedded, skipped = embed_pois(data_dir)
    print(f"Done. Embedded: {embedded}, Skipped: {skipped}")
