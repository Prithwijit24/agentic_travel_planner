"""Load parsed data into Neo4j.

Creates:
  (:Place {poi_id, name, lat, long})                 -- countries/regions/cities
  (:POI {poi_id, name, category, lat, long, ...})     -- see/do/eat/drink/sleep/buy
  (:Place)-[:LOCATED_IN]->(:Place)                    -- hierarchy (city -> region -> country)
  (:POI)-[:LOCATED_IN]->(:Place)                      -- listing belongs to its page/city
  (:POI)-[:NEAR {distance_km}]->(:POI)                -- computed from coordinates

Run:
    python -m agentic_tour_planner.graphdb.load_neo4j [data-dir]
"""

from __future__ import annotations

import json
import math
import sys
from itertools import combinations
from pathlib import Path

from loguru import logger
from neo4j import GraphDatabase

from agentic_tour_planner.config.settings import get_settings

NEAR_THRESHOLD_KM = 3.0
BATCH_SIZE = 1000


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def grid_key(lat, lon, cell_deg=0.05):
    return (round(lat / cell_deg), round(lon / cell_deg))


def load_places(driver, pages_path):
    pages = [json.loads(line) for line in open(pages_path, encoding="utf-8") if line.strip()]
    with driver.session() as session:
        for i in range(0, len(pages), BATCH_SIZE):
            batch = pages[i:i + BATCH_SIZE]
            session.run(
                """
                UNWIND $rows AS row
                MERGE (p:Place {poi_id: row.poi_id})
                SET p.name = row.page_title,
                    p.lat = row.lat,
                    p.long = row.long
                """,
                rows=batch,
            )
    logger.info(f"Loaded {len(pages)} Place nodes.")
    return pages


def load_pois(driver, pois_path):
    pois = [json.loads(line) for line in open(pois_path, encoding="utf-8") if line.strip()]
    with driver.session() as session:
        for i in range(0, len(pois), BATCH_SIZE):
            batch = pois[i:i + BATCH_SIZE]
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
                    poi.long_description = row.long_description,
                    poi.base_page = row.base_page
                WITH poi, row
                MATCH (place:Place {name: row.base_page})
                MERGE (poi)-[:LOCATED_IN]->(place)
                """,
                rows=batch,
            )
    logger.info(f"Loaded {len(pois)} POI nodes (+ LOCATED_IN to their base page).")
    return pois


def load_hierarchy(driver, edges_path):
    edges = [json.loads(line) for line in open(edges_path, encoding="utf-8") if line.strip()]
    with driver.session() as session:
        for i in range(0, len(edges), BATCH_SIZE):
            batch = edges[i:i + BATCH_SIZE]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (child:Place {poi_id: row.child_poi_id})
                MATCH (parent:Place {poi_id: row.parent_poi_id})
                MERGE (child)-[:LOCATED_IN]->(parent)
                """,
                rows=batch,
            )
    logger.info(f"Loaded {len(edges)} Place hierarchy edges.")


def compute_and_load_near_edges(driver, pois):
    geo_pois = [p for p in pois if p.get("lat") and p.get("long")]

    buckets = {}
    for p in geo_pois:
        key = grid_key(p["lat"], p["long"])
        buckets.setdefault(key, []).append(p)

    near_edges = []
    for key, group in buckets.items():
        neighbor_keys = [(key[0] + dx, key[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]
        candidates = []
        for nk in neighbor_keys:
            candidates.extend(buckets.get(nk, []))

        for a, b in combinations(candidates, 2):
            if a["poi_id"] >= b["poi_id"]:
                continue
            dist = haversine_km(a["lat"], a["long"], b["lat"], b["long"])
            if dist <= NEAR_THRESHOLD_KM:
                near_edges.append({"a": a["poi_id"], "b": b["poi_id"], "distance_km": round(dist, 2)})

    with driver.session() as session:
        for i in range(0, len(near_edges), BATCH_SIZE):
            batch = near_edges[i:i + BATCH_SIZE]
            session.run(
                """
                UNWIND $rows AS row
                MATCH (a:POI {poi_id: row.a})
                MATCH (b:POI {poi_id: row.b})
                MERGE (a)-[r:NEAR]-(b)
                SET r.distance_km = row.distance_km
                """,
                rows=batch,
            )
    logger.info(f"Loaded {len(near_edges)} NEAR edges (threshold {NEAR_THRESHOLD_KM}km).")


def main(data_dir: str | None = None):
    data_path = Path(data_dir) if data_dir else Path(".")
    settings = get_settings()

    uri = getattr(settings, "neo4j_uri", "bolt://localhost:7687")
    user = getattr(settings, "neo4j_user", "neo4j")
    password = getattr(settings, "neo4j_password", "")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        session.run("CREATE INDEX place_poi_id IF NOT EXISTS FOR (p:Place) ON (p.poi_id)")
        session.run("CREATE INDEX poi_poi_id IF NOT EXISTS FOR (p:POI) ON (p.poi_id)")
        session.run("CREATE INDEX poi_category IF NOT EXISTS FOR (p:POI) ON (p.category)")

    load_places(driver, str(data_path / "pages.jsonl"))
    pois = load_pois(driver, str(data_path / "pois.jsonl"))
    load_hierarchy(driver, str(data_path / "hierarchy_edges.jsonl"))
    compute_and_load_near_edges(driver, pois)

    driver.close()
    logger.info("Neo4j load complete.")


if __name__ == "__main__":
    if not Path("pages.jsonl").exists() and len(sys.argv) < 2:
        print("Usage: python -m agentic_tour_planner.graphdb.load_neo4j [data-dir]")
        sys.exit(1)
    main(sys.argv[1] if len(sys.argv) > 1 else None)
