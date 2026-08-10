# Wikivoyage → Neo4j Ingestion Pipeline

## What this produces

```
(:Place {poi_id, name, lat, long})
(:POI   {poi_id, name, category, address, lat, long, hours, price, phone,
         long_description, base_page})

(:Place)-[:LOCATED_IN]->(:Place)   -- e.g. (Gangtok)-[:LOCATED_IN]->(East Sikkim)
(:POI)-[:LOCATED_IN]->(:Place)     -- e.g. (Rumtek Monastery)-[:LOCATED_IN]->(Gangtok)
(:POI)-[:NEAR {distance_km}]-(:POI) -- computed from coordinates, undirected
```

`category` on POI is one of: see, do, eat, drink, sleep, buy, listing.

## How to run, in order

```bash
pip install -r requirements.txt --break-system-packages

# 1. Download the dump (do this once, it's several GB)
wget https://dumps.wikimedia.org/enwikivoyage/latest/enwikivoyage-latest-pages-articles.xml.bz2
bzip2 -d enwikivoyage-latest-pages-articles.xml.bz2

# 2. Parse wikitext -> structured JSONL
python 1_parse_dump.py enwikivoyage-latest-pages-articles.xml
# produces: pages.jsonl, pois.jsonl

# 3. Infer Country/Region/City hierarchy
python 2_infer_hierarchy.py
# produces: hierarchy_edges.jsonl, orphans.jsonl

# 4. Load everything into Neo4j
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=<your password>
python 3_load_neo4j.py
```

## Sanity-check queries once loaded

```cypher
// How many POIs did we get for Sikkim's cities?
MATCH (poi:POI)-[:LOCATED_IN]->(place:Place)
WHERE place.name CONTAINS 'Sikkim' OR place.name CONTAINS 'Gangtok'
RETURN place.name, count(poi) AS poi_count ORDER BY poi_count DESC

// Spot-check NEAR edges make sense
MATCH (a:POI {name: 'Rumtek Dharma Chakra Centre'})-[r:NEAR]-(b:POI)
RETURN a.name, b.name, r.distance_km ORDER BY r.distance_km

// Check hierarchy chain resolves up to a country
MATCH path = (c:Place {name: 'Gangtok'})-[:LOCATED_IN*]->(top:Place)
RETURN [n IN nodes(path) | n.name] AS chain
```

## Known limitations — expect to iterate here

1. **Hierarchy inference is a heuristic**, matching category names to page
   titles. Wikivoyage isn't 100% consistent about this, so check
   `orphans.jsonl` — pages with no inferred parent. Some are legitimately
   top-level (countries, continents); others need a manual fix (e.g. a
   lookup table you maintain for edge cases).

2. **Not every listing has coordinates.** POIs missing `lat`/`long` won't
   get `NEAR` edges. You can still reach them via `LOCATED_IN` to their
   city, which is usually enough for city-level planning.

3. **`long_description` is stripped wikitext**, which is serviceable but
   sometimes rough (leftover formatting, external link text, etc). This
   is exactly the text you'll embed into Chroma next — worth running a
   cleanup/normalization pass (or a one-time LLM rewrite) before you
   embed it, since retrieval quality depends on clean text.

4. **`NEAR_THRESHOLD_KM` (3km default)** and the grid bucket size in
   `3_load_neo4j.py` control how many NEAR edges get created — tune
   based on whether you want tight walking-distance clusters or a wider
   "same neighborhood" radius.

5. **No transit edges yet.** This pipeline gives you geography and
   proximity, not "bus from X to Y takes 2hrs." That has to come from a
   separate source (a transit dataset, or your on-the-fly search/crawl
   agent filling gaps) and gets added as a distinct `(:Place)-[:CONNECTED_TO]->(:Place)`
   edge type later.

## Next step

Once this is loaded, `pois.jsonl`'s `long_description` field is also
your source text for embedding into Chroma (Phase 1's vector side) —
same POIs, same `poi_id` as the join key between the two databases.
