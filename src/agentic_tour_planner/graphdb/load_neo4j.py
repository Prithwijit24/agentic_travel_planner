"""Load LLM-enriched POIs into Neo4j.

Creates:
  (:Place {poi_id, name, lat, long})                            -- cities/regions
  (:POI {poi_id, name, category, region, lat, long, tags, rich_description})
  (:POI)-[:LOCATED_IN]->(:Place)                                 -- hierarchy
  (:POI)-[:LOCATED_IN]->(:Place)                                 -- POI belongs to its page
  (:POI)-[:NEAR {distance_km}]->(:POI)                           -- proximity
  (:POI)-[:RELATED {shared_tags, rel_type}]->(:POI)              -- shared themes/tags

Reads enriched_pois.jsonl (from enrich_pois.py) for LLM-generated content,
plus pages.jsonl and hierarchy_edges.jsonl (from parse_dump.py) for structure.

Run:
    python -m agentic_tour_planner.graphdb.load_neo4j [data-dir]
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from itertools import combinations
from pathlib import Path

from loguru import logger
from neo4j import GraphDatabase

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.llm.provider import LLMProvider


def _graph_load_settings():
    s = get_settings()
    return s.graph_near_threshold_km, s.graph_load_batch_size


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def grid_key(lat, lon, cell_deg=0.05):
    return (round(lat / cell_deg), round(lon / cell_deg))


def load_places(driver, pages_path, batch_size):
    with Path(pages_path).open(encoding="utf-8") as f:
        pages = [json.loads(line) for line in f if line.strip()]
    with driver.session() as session:
        for i in range(0, len(pages), batch_size):
            batch = pages[i : i + batch_size]
            session.run(
                """
                UNWIND $rows AS row
                MERGE (p:Place {poi_id: row.poi_id})
                SET p.name = row.page_title,
                    p.lat = row.lat,
                    p.long = row.long
                """,
                {"rows": batch},
            )
    logger.info(f"Loaded {len(pages)} Place nodes.")
    return pages


def load_pois(driver, enriched_path, batch_size):
    with Path(enriched_path).open(encoding="utf-8") as f:
        pois = [json.loads(line) for line in f if line.strip()]
    with driver.session() as session:
        for i in range(0, len(pois), batch_size):
            batch = pois[i : i + batch_size]
            session.run(
                """
                UNWIND $rows AS row
                MERGE (poi:POI {poi_id: row.poi_id})
                SET poi.name = row.name,
                    poi.category = row.category,
                    poi.address = row.address,
                    poi.lat = row.lat,
                    poi.long = row.long,
                    poi.hours = row.hours,
                    poi.price = row.price,
                    poi.phone = row.phone,
                    poi.base_page = row.base_page,
                    poi.region = row.base_page,
                    poi.long_description = row.long_description,
                    poi.rich_description = row.rich_description,
                    poi.tags = row.tags
                WITH poi, row
                MATCH (place:Place {name: row.base_page})
                MERGE (poi)-[:LOCATED_IN]->(place)
                """,
                {"rows": batch},
            )
    logger.info(f"Loaded {len(pois)} POI nodes (+ LOCATED_IN + tags).")
    return pois


def load_hierarchy(driver, edges_path, batch_size):
    with Path(edges_path).open(encoding="utf-8") as f:
        edges = [json.loads(line) for line in f if line.strip()]
    with driver.session() as session:
        for i in range(0, len(edges), batch_size):
            batch = edges[i : i + batch_size]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (child:Place {poi_id: row.child_poi_id})
                MATCH (parent:Place {poi_id: row.parent_poi_id})
                MERGE (child)-[:LOCATED_IN]->(parent)
                """,
                {"rows": batch},
            )
    logger.info(f"Loaded {len(edges)} Place hierarchy edges.")


async def _describe_relationship(provider: LLMProvider, poi_a: dict, poi_b: dict) -> dict | None:
    s = get_settings()
    prompt = s.NEAR_RELATIONSHIP_USER_PROMPT.format(
        name_a=poi_a.get("name", ""),
        category_a=poi_a.get("category", ""),
        tags_a=", ".join(poi_a.get("tags", [])),
        name_b=poi_b.get("name", ""),
        category_b=poi_b.get("category", ""),
        tags_b=", ".join(poi_b.get("tags", [])),
    )
    try:
        result = await provider.complete_json(prompt, system_prompt=s.NEAR_RELATIONSHIP_SYSTEM_PROMPT)
        return result
    except Exception as e:
        logger.warning("LLM edge description failed for {}-{}: {}".format(poi_a.get("poi_id"), poi_b.get("poi_id"), e))
        return None


async def compute_and_load_edges(driver, pois, batch_size, use_llm=True):
    near_threshold_km, _ = _graph_load_settings()
    geo_pois = [p for p in pois if p.get("lat") and p.get("long")]

    buckets = {}
    for p in geo_pois:
        key = grid_key(p["lat"], p["long"])
        buckets.setdefault(key, []).append(p)

    near_edges = []
    for key, _group in buckets.items():
        neighbor_keys = [(key[0] + dx, key[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        candidates = []
        for nk in neighbor_keys:
            candidates.extend(buckets.get(nk, []))

        for a, b in combinations(candidates, 2):
            if a["poi_id"] >= b["poi_id"]:
                continue
            dist = haversine_km(a["lat"], a["long"], b["lat"], b["long"])
            if dist <= near_threshold_km:
                near_edges.append({"a": a["poi_id"], "b": b["poi_id"], "distance_km": round(dist, 2)})

    # Build tag index for deterministic RELATED edges
    tag_index: dict[str, list[str]] = {}
    for p in geo_pois:
        for tag in p.get("tags", []):
            tag_index.setdefault(tag, []).append(p["poi_id"])

    related_edges: dict[tuple[str, str], set[str]] = {}
    for tag, poi_ids in tag_index.items():
        if len(poi_ids) < 2:
            continue
        for a, b in combinations(sorted(poi_ids), 2):
            related_edges.setdefault((a, b), set()).add(tag)

    # LLM-described relationships for nearby pairs
    llm_edges: dict[tuple[str, str], dict] = {}
    if use_llm and near_edges:
        provider = LLMProvider()
        poi_map = {p["poi_id"]: p for p in geo_pois}
        logger.info(f"Generating LLM relationship descriptions for {len(near_edges)} nearby pairs...")

        for edge in near_edges:
            a = poi_map.get(edge["a"])
            b = poi_map.get(edge["b"])
            if not a or not b:
                continue
            desc = await _describe_relationship(provider, a, b)
            if desc:
                llm_edges[(edge["a"], edge["b"])] = desc

    with driver.session() as session:
        # NEAR edges
        for i in range(0, len(near_edges), batch_size):
            batch = near_edges[i : i + batch_size]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (a:POI {poi_id: row.a})
                MATCH (b:POI {poi_id: row.b})
                MERGE (a)-[r:NEAR]-(b)
                SET r.distance_km = row.distance_km
                """,
                {"rows": batch},
            )

        # RELATED edges (from shared tags + LLM)
        rel_batch = []
        for (a_id, b_id), shared in related_edges.items():
            rec = {"a": a_id, "b": b_id, "shared_tags": list(shared)}
            llm_desc = llm_edges.get((a_id, b_id)) or llm_edges.get((b_id, a_id))
            if llm_desc:
                rec["rel_type"] = llm_desc.get("rel_type", "")
                rec["description"] = llm_desc.get("description", "")
            rel_batch.append(rec)

        for i in range(0, len(rel_batch), batch_size):
            batch = rel_batch[i : i + batch_size]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (a:POI {poi_id: row.a})
                MATCH (b:POI {poi_id: row.b})
                MERGE (a)-[r:RELATED]-(b)
                SET r.shared_tags = row.shared_tags,
                    r.rel_type = row.rel_type,
                    r.description = row.description
                """,
                {"rows": batch},
            )

    logger.info(f"Loaded {len(near_edges)} NEAR edges, {len(related_edges)} RELATED edges.")
    return near_edges, related_edges


def clear_graph(driver):
    """Remove POI/Place nodes and all relationships (preserves other apps' data)."""
    with driver.session() as session:
        session.run("MATCH (p:POI) DETACH DELETE p")
        session.run("MATCH (p:Place) DETACH DELETE p")
    logger.info("Cleared POI/Place nodes and their relationships.")


def main(data_dir: str | None = None, use_llm=True):
    data_path = Path(data_dir) if data_dir else Path()
    settings = get_settings()

    uri = getattr(settings, "neo4j_uri", "bolt://localhost:7687")
    user = getattr(settings, "neo4j_user", "neo4j")
    password = getattr(settings, "neo4j_password", "")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        session.run("CREATE INDEX place_poi_id IF NOT EXISTS FOR (p:Place) ON (p.poi_id)")
        session.run("CREATE INDEX poi_poi_id IF NOT EXISTS FOR (p:POI) ON (p.poi_id)")
        session.run("CREATE INDEX poi_category IF NOT EXISTS FOR (p:POI) ON (p.poi_id)")

    near_threshold_km, batch_size = _graph_load_settings()

    clear_graph(driver)
    load_places(driver, str(data_path / "pages.jsonl"), batch_size)
    pois = load_pois(driver, str(data_path / "enriched_pois.jsonl"), batch_size)
    load_hierarchy(driver, str(data_path / "hierarchy_edges.jsonl"), batch_size)
    asyncio.run(compute_and_load_edges(driver, pois, batch_size, use_llm=use_llm))

    driver.close()
    logger.info(f"Neo4j load complete. NEAR threshold={near_threshold_km}km")


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else None
    main(data_dir)
