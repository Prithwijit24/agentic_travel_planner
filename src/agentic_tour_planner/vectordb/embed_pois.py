"""Embed POI descriptions into ChromaDB.

Input:  pois.jsonl (from parse_dump.py)
Output: ChromaDB collection 'poi_descriptions' with embedded documents

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
    """Read pois.jsonl and embed into ChromaDB. Returns (embedded_count, skipped_count)."""
    data_path = Path(data_dir) if data_dir else Path(".")
    pois_file = data_path / "pois.jsonl"

    if not pois_file.exists():
        raise FileNotFoundError(f"pois.jsonl not found in {data_path}")

    pois = [json.loads(line) for line in open(pois_file, encoding="utf-8") if line.strip()]

    ids = []
    documents = []
    metadatas = []
    skipped = 0

    for poi in pois:
        description = poi.get("long_description", "").strip()
        if not description or len(description) < 10:
            skipped += 1
            continue

        ids.append(poi["poi_id"])
        documents.append(description)
        metadatas.append({
            "poi_id": poi["poi_id"],
            "name": poi.get("name", ""),
            "category": poi.get("category", ""),
            "region": poi.get("base_page", ""),
            "lat": poi.get("lat"),
            "long": poi.get("long"),
        })

    if ids:
        client = get_vector_db()
        # Clear existing collection data for clean re-embed
        col = client.get_collection()
        existing = col.get()["ids"]
        if existing:
            col.delete(ids=existing)
        client.add_pois(ids=ids, documents=documents, metadatas=metadatas)

    logger.info(f"Embedded {len(ids)} POIs, skipped {skipped} (empty/short descriptions)")
    return len(ids), skipped


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    embedded, skipped = embed_pois(data_dir)
    print(f"Done. Embedded: {embedded}, Skipped: {skipped}")
