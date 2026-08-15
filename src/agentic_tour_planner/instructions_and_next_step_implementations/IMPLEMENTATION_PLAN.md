# Agentic Tour Planner — Implementation Plan

This plan upgrades the existing repo (FastAPI + Streamlit + CLI + LLM
provider + heuristic-fallback workers) into a hybrid graph/vector RAG
system with deterministic sequencing and a real multi-agent critique
loop. Follow phases IN ORDER. Do not skip ahead — later phases depend
on earlier ones existing and passing their "Definition of done".

Existing repo structure (for reference, do not break these):
```
src/agentic_tour_planner/
  llm/provider.py              <- KEEP. Multi-provider LLM adapter, reuse everywhere.
  services/planning_workers.py <- Will be REPLACED by Phase 6 agents.
  pipeline/                    <- Orchestration. Will be REWIRED in Phase 11.
  services/news_service.py     <- KEEP. Reuse as-is for Phase 8 freshness agent.
  images/                      <- KEEP, unrelated to this plan.
  api/                         <- KEEP, endpoints stay the same shape, internals change.
  app/streamlit_app.py         <- KEEP, only the backend call changes.
```

---

## PHASE 0 — Environment setup

- [ ] Install Neo4j locally (Docker is easiest):
      `docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/testpassword neo4j:5`
- [ ] Confirm Neo4j browser loads at `http://localhost:7474` and you can log in with `neo4j` / `testpassword`.
- [ ] Install ChromaDB: `pip install chromadb --break-system-packages`
- [ ] Add new dependencies to `pyproject.toml`: `mwparserfromhell`, `neo4j`, `chromadb`, `langgraph`, `langchain-core`.
- [ ] Create new top-level package folders (empty `__init__.py` in each):
      ```
      src/agentic_tour_planner/graphdb/
      src/agentic_tour_planner/vectordb/
      src/agentic_tour_planner/retrieval/
      src/agentic_tour_planner/sequencing/
      src/agentic_tour_planner/agents/
      src/agentic_tour_planner/narration/
      ```
- [ ] Add `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `CHROMA_PERSIST_DIR` to `.env` and to whatever config loader the repo already uses (check `src/agentic_tour_planner/` for an existing `config.py` or `settings.py` — use it, do not create a second config system).

**Definition of done:** `docker ps` shows neo4j running; `python -c "import chromadb, neo4j, langgraph"` runs with no import errors.

---

## PHASE 1 — Wikivoyage → Neo4j ingestion

- [ ] Create `src/agentic_tour_planner/graphdb/parse_dump.py` — copy logic from the `1_parse_dump.py` script provided earlier in this conversation. Adjust import paths only, logic stays the same.
- [ ] Create `src/agentic_tour_planner/graphdb/infer_hierarchy.py` — copy from `2_infer_hierarchy.py`.
- [ ] Create `src/agentic_tour_planner/graphdb/load_neo4j.py` — copy from `3_load_neo4j.py`, but read `NEO4J_URI`/`USER`/`PASSWORD` from the repo's config loader instead of raw `os.environ`.
- [ ] Create `src/agentic_tour_planner/graphdb/client.py` — a thin wrapper class `GraphDBClient` with a single shared `neo4j.GraphDatabase.driver` instance and a `run_query(cypher, params) -> list[dict]` method. Every other module in this plan that talks to Neo4j imports this client — never opens its own driver.
- [ ] Download a SMALL test slice first — do not run on the full dump yet. Use `enwikivoyage` API export for just Sikkim + 2-3 nearby pages, or manually truncate the XML to the first ~500 `<page>` elements for a smoke test.
- [ ] Run `parse_dump.py` on the small slice. Confirm `pois.jsonl` and `pages.jsonl` are created and non-empty.
- [ ] Run `infer_hierarchy.py`. Confirm `hierarchy_edges.jsonl` is created. Open `orphans.jsonl` and manually check it's mostly top-level pages (countries/regions), not bugs.
- [ ] Run `load_neo4j.py`. Confirm no errors.
- [ ] Open Neo4j browser, run: `MATCH (n) RETURN count(n)` — confirm node count > 0.
- [ ] Run: `MATCH (poi:POI)-[:LOCATED_IN]->(place:Place) RETURN place.name, count(poi) LIMIT 10` — confirm real place names and POI counts appear (not nulls).
- [ ] ONLY after the small slice works end-to-end: download the full `enwikivoyage-latest-pages-articles.xml.bz2` dump and re-run all three scripts on the full file.
- [ ] Full run may take a long time — add basic progress logging (already present in `parse_dump.py`) and run it as a background/detached process, not interactively.
- [ ] Add a `post_clean(text: str) -> str` helper to `graphdb/parse_dump.py`, called right after `clean_wikitext_to_plain()`, to catch what `mwparserfromhell.strip_code()` leaves behind (collapsed whitespace, dangling "See also" fragments, stray " ." spacing artifacts). Example:
      ```python
      import re
      def post_clean(text: str) -> str:
          text = re.sub(r'\s+', ' ', text).strip()
          text = re.sub(r'\bSee also\b\.?$', '', text)
          text = re.sub(r'\s+\.', '.', text)
          return text.strip()
      ```
- [ ] Spot-check 10-15 random `long_description` values after the small-slice run — confirm no leftover `[[`, `{{`, `<ref>`, or dangling link-anchor text remains. Fix `post_clean` iteratively if patterns are found, before running on the full dump (re-cleaning the full dump later is expensive — get this right on the small slice first).

**Definition of done:** Neo4j contains `:Place` and `:POI` nodes for the full Wikivoyage dump, with `:LOCATED_IN` and `:NEAR` edges. Sanity queries in the README (from the earlier script package) all return non-empty, plausible results.

---

## PHASE 2 — Chroma vector store from the same POIs

- [ ] Create `src/agentic_tour_planner/vectordb/client.py` — `VectorDBClient` wrapping a persistent `chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)`, with one collection named `poi_descriptions`.
- [ ] Create `src/agentic_tour_planner/vectordb/embed_pois.py`:
  - [ ] Read `pois.jsonl` (same file produced in Phase 1).
  - [ ] For each POI, embed `long_description` (skip POIs with empty/near-empty descriptions — log how many are skipped).
  - [ ] Store in Chroma with `id=poi_id` and metadata: `{poi_id, name, category, region: base_page, lat, long}`.
  - [ ] Batch the `.add()` calls (e.g. 200 at a time) — do not call `.add()` once per POI, it's slow.
- [ ] Run `embed_pois.py` on the small test slice first. Confirm collection count matches expected POI count (minus skipped empty ones).
- [ ] Sanity test: query Chroma directly with `collection.query(query_texts=["monastery nature"], n_results=5)` and confirm results look topically relevant.
- [ ] Run on the full POI set once the small test passes.

**Definition of done:** Chroma collection `poi_descriptions` contains one embedded document per POI with `long_description` text, keyed by the same `poi_id` used in Neo4j. A test query returns topically relevant POIs.

---

## PHASE 3 — Deterministic retrieval layer (no LLM)

- [ ] Create `src/agentic_tour_planner/retrieval/graph_retrieval.py`:
  - [ ] Function `get_candidates(destination: str) -> list[str]` — Cypher query returning all `poi_id`s under the given `Place` name (case-insensitive match, also try partial/CONTAINS match if exact fails).
  - [ ] Function `enrich(poi_ids: list[str]) -> list[dict]` — returns full POI records (all Neo4j properties) for the given IDs.
- [ ] Create `src/agentic_tour_planner/retrieval/vector_retrieval.py`:
  - [ ] Function `filter_by_interest(poi_ids: list[str], interest_tags: list[str], top_k: int = 40) -> list[str]` — builds a query string by joining `interest_tags`, queries Chroma with a metadata filter restricting to the given `poi_ids`, returns the top-k matching `poi_id`s.
- [ ] Create `src/agentic_tour_planner/retrieval/pipeline.py`:
  - [ ] Function `retrieve(destination: str, interest_tags: list[str]) -> list[dict]` that chains: `get_candidates` → `filter_by_interest` → `enrich`. Returns list of enriched POI dicts.
- [ ] Write a standalone test script `scripts/test_retrieval.py` that calls `retrieve("Sikkim", ["Nature", "Monasteries"])` and prints the result count + first 3 POI names.
- [ ] Run it. Confirm: (a) it runs in well under 1 second, (b) results are Sikkim POIs, (c) results plausibly relate to nature/monasteries.

**Definition of done:** `retrieve()` returns a correct, fast, LLM-free shortlist for any destination + interest tag combination present in the data.

---

## PHASE 3B — Dynamic interest tags (replaces the static Interests filter list)

Rationale: a fixed, hardcoded tag list ("Nature", "Monasteries", ...) forces
users to know what's relevant at a destination before they've seen anything
about it. Instead, tags shown in the UI should be generated FROM the actual
data for the selected destination, and Interests should be optional with a
sensible default — not a required gate.

- [ ] Add `get_available_tags(destination: str) -> list[str]` to `retrieval/graph_retrieval.py`:
      ```cypher
      MATCH (poi:POI)-[:LOCATED_IN*1..3]->(place:Place {name: $destination})
      RETURN DISTINCT poi.category AS tag, count(poi) AS cnt
      ORDER BY cnt DESC
      ```
      Return the `tag` list (optionally cap to top ~10 most common categories so the
      UI dropdown isn't overwhelming). If POIs later get richer free-form `tags`
      (not just the 6 fixed categories), extend this query to unwind and count those too.
- [ ] Add a new API endpoint, e.g. `GET /destinations/{name}/interests`, in `api/`, calling `get_available_tags`. Keep response shape simple: `{"tags": ["Monasteries", "Nature", "Heritage Ruins", ...]}`.
- [ ] Update `app/streamlit_app.py`: when the Destination field changes, call this new endpoint and repopulate the Interests multi-select options with the returned tags — do NOT ship a hardcoded tag list in the frontend anymore.
- [ ] Make Interests optional in both the UI and the request schema (`api/` request model) — remove any "must select at least one" validation if present.
- [ ] Add `get_balanced_default_pois(destination: str, limit_per_category: int = 3) -> list[str]` to `retrieval/graph_retrieval.py` — used when the user submits with NO interests selected. Pulls a small, even spread of POIs across all distinct categories present at that destination (so no single type like "Eat" dominates the default itinerary).
- [ ] In `retrieval/pipeline.py`'s `retrieve()` function: if `interest_tags` is empty/None, call `get_balanced_default_pois()` instead of `filter_by_interest()` — skip the vector step entirely in this case, since there's no preference text to match against.
- [ ] Test: request Sikkim with no interests selected — confirm the result includes POIs from multiple categories (not all monasteries, not all restaurants), and that the itinerary still generates end-to-end.
- [ ] Test: request Sikkim's dynamic tags endpoint — confirm returned tags match what's actually in Neo4j for Sikkim (cross-check against a manual Cypher query), and that requesting a different destination (e.g. "Kyoto") returns a different, destination-appropriate tag list.

**Definition of done:** The Interests UI is populated per-destination from real data instead of a static list, is fully optional, and omitting it still produces a reasonable, category-balanced itinerary.

---

## PHASE 4 — Deterministic sequencing (no LLM)

- [ ] Create `src/agentic_tour_planner/sequencing/bin_packer.py`:
  - [ ] Function `sequence(pois: list[dict], duration_days: int, daily_hour_budget: float = 8.0) -> list[dict]`.
  - [ ] Group POIs by `base_city` (or `base_page`).
  - [ ] Order city groups by proximity/feasibility — if Neo4j has no transit edges yet, just order by whatever grouping keeps duration_days achievable (simple heuristic: largest POI cluster first, or alphabetical if no better signal — flag this as a TODO to improve once transit data exists).
  - [ ] Within a city group, greedily add POIs to the current day while `sum(avg_visit_hrs) <= daily_hour_budget`; start a new day when the budget is exceeded or the day count is reached.
  - [ ] If total feasible-day capacity is less than the number of available POIs, drop the lowest-priority ones (priority = vector similarity rank from Phase 3, pass this through).
  - [ ] Output shape: `[{"day": 1, "city": "Gangtok", "pois": [poi_dict, ...]}, ...]`
- [ ] Write `scripts/test_sequencing.py`: take Phase 3's retrieval output for Sikkim, run `sequence(..., duration_days=4)`, print the day-by-day POI names.
- [ ] Run it twice — confirm identical output both times (proves determinism).
- [ ] Manually check the printed output for obvious feasibility problems (e.g. two far-apart cities crammed into one day) — if Neo4j lacks `avg_visit_hrs` for many POIs, add a sane default (e.g. 1.5 hrs) in this function rather than crashing.

**Definition of done:** `sequence()` is deterministic (same input → same output every run), respects the daily hour budget, and produces a day-by-day skeleton with no missing fields.

---

## PHASE 5 — Cost estimation (no LLM)

- [ ] Check if `services/planning_workers.py` already has cost-calculation logic (README mentions a "budget worker") — if yes, extract the pure-math parts into `src/agentic_tour_planner/sequencing/cost.py` and reuse; do not duplicate.
- [ ] Function `estimate_cost(day_skeleton: list[dict], travelers: int, budget_tier: str) -> dict` — sums `cost_per_person` across POIs per day, adds hotel/food estimates from a small lookup table keyed by `budget_tier` (budget/midrange/luxury), returns per-day subtotal + grand total + per-person total (matching the shape shown in the sample CLI output from earlier in this conversation).
- [ ] Test with Phase 4's output — confirm the returned numbers are sane (no negative costs, no missing days).

**Definition of done:** `estimate_cost()` produces the same cost breakdown shape as the current CLI output, purely from arithmetic — zero LLM calls.

---

## PHASE 6 — Multi-agent critique loop (LangGraph) — replaces `planning_workers.py`'s LLM-decision parts

- [ ] Create `src/agentic_tour_planner/agents/state.py` — define a `TripState` (TypedDict or pydantic model) holding: `trip_meta`, `day_skeleton`, `cost_summary`, `critiques: list[str]`, `revision_count: int`.
- [ ] Create `src/agentic_tour_planner/agents/budget_agent.py` — function `critique_budget(state: TripState) -> TripState` that:
  - [ ] Compares `cost_summary` against a per-person/day threshold table for `budget_tier`.
  - [ ] If over threshold, appends a critique string to `state["critiques"]` describing which day/POI to reconsider (e.g. "Day 2 exceeds midrange budget, consider dropping X").
  - [ ] Uses the existing `llm/provider.py` ONLY to phrase the critique in natural language if you want it more readable — the over/under-budget DECISION itself must be plain arithmetic, not LLM judgment.
- [ ] Create `src/agentic_tour_planner/agents/timing_agent.py` — function `critique_timing(state: TripState) -> TripState`:
  - [ ] Checks each day's total `avg_visit_hrs` + estimated inter-POI travel time against `daily_hour_budget`.
  - [ ] Flags infeasible days with a critique string.
- [ ] Create `src/agentic_tour_planner/agents/planner_agent.py` — function `resolve_critiques(state: TripState) -> TripState`:
  - [ ] Takes accumulated critiques, calls the LLM (via `llm/provider.py`) ONCE with the current skeleton + critiques, asks for a specific revision instruction in structured JSON (e.g. `{"action": "drop_poi", "poi_id": "...", "day": 2}` or `{"action": "swap_poi", ...}`).
  - [ ] Applies the returned instruction to `state["day_skeleton"]` in code (not by trusting the LLM to rewrite the whole skeleton — only apply the specific small edit it returned).
  - [ ] Increments `state["revision_count"]`.
- [ ] Create `src/agentic_tour_planner/agents/graph.py` — wire these into a LangGraph `StateGraph`:
  - [ ] Nodes: `budget_agent`, `timing_agent`, `planner_agent`.
  - [ ] Edges: `budget_agent` → `timing_agent` → conditional edge: if `critiques` is non-empty AND `revision_count < 2`, go to `planner_agent` → back to `budget_agent`; else END.
  - [ ] Hard cap `revision_count` at 2 to prevent infinite loops — after 2 revisions, exit regardless of remaining critiques and pass them through as "known limitations" to the narration step.
- [ ] Write `scripts/test_critique_loop.py`: feed it Phase 4/5's Sikkim output, run the graph, print the number of revisions and final skeleton.
- [ ] Run it. Confirm it terminates (does not hang), and that if you artificially inflate a POI's cost, the loop actually drops/swaps something.

**Definition of done:** The LangGraph critique loop runs to completion in under ~15 seconds, terminates deterministically (never infinite-loops), and demonstrably changes the skeleton when a constraint is violated.

---

## PHASE 7 — RAG query reformulation (upgrades Phase 3's vector step)

- [ ] Create `src/agentic_tour_planner/agents/retrieval_agent.py`:
  - [ ] Function `reformulate_and_retrieve(destination: str, interest_tags: list[str]) -> list[dict]`.
  - [ ] Call the LLM once with the interest tags, ask it to return 3-4 reformulated search phrases as a JSON list (e.g. `["Buddhist monasteries heritage", "quiet mountain valleys lakes", ...]`).
  - [ ] Run `filter_by_interest` (Phase 3) once per reformulated phrase, merge + dedupe results.
  - [ ] Optionally: check region/category coverage of the merged results (e.g. count distinct `base_page` values) — if coverage looks thin (fewer than 2 distinct sub-regions), fire one more reformulated query targeting the gap.
- [ ] Replace the plain `filter_by_interest` call in `retrieval/pipeline.py` with this agent's output, behind a feature flag (e.g. `USE_RAG_REFORMULATION=true` in config) so you can A/B compare against the simple version.
- [ ] Test: compare result sets for `("Sikkim", ["Nature", "Monasteries"])` between plain retrieval (Phase 3) and reformulated retrieval (Phase 7) — confirm the reformulated version returns a broader/more relevant set (e.g. covers West Sikkim too, not just Gangtok).

**Definition of done:** Reformulated retrieval demonstrably returns broader, still-relevant coverage than single-query retrieval, using at most 4-5 total LLM+vector calls.

---

## PHASE 8 — Freshness / ReAct agent (conditional, live extraction)

- [ ] Create `src/agentic_tour_planner/agents/freshness_agent.py`:
  - [ ] Function `check_and_refresh(poi: dict) -> dict` — checks if `poi["long_description"]` is empty OR a `last_verified` field (add this field to Neo4j schema if missing) is older than 6 months.
  - [ ] If stale: reuse the repo's EXISTING `services/news_service.py` search/crawl capability (README says it already has DDGS fallback) — do not build a new search client, wire into the existing one.
  - [ ] Parse/summarize the fetched content with one LLM call into the same POI schema fields (`long_description`, `short_highlight`).
  - [ ] Write the refreshed fields back to BOTH Neo4j (via `GraphDBClient`) and Chroma (via `VectorDBClient`, upsert) with an updated `last_verified` timestamp.
- [ ] Wire this as a filter step in `retrieval/pipeline.py`: after Phase 3/7 retrieval, run `check_and_refresh` only on POIs flagged stale — most POIs should skip this entirely.
- [ ] Test: manually blank out one POI's `long_description` in Neo4j, re-run retrieval including that POI, confirm the freshness agent fires, fills it in, and the field is now populated in both databases on the next lookup (i.e. it doesn't refetch every time — caching works).

**Definition of done:** Freshness checks add negligible latency for the common case (cached, fresh data) and correctly backfill + persist missing data for the stale case, without re-fetching already-fresh POIs.

---

## PHASE 9 — Single-pass LLM narration (replaces multi-pass generation)

- [ ] Create `src/agentic_tour_planner/narration/narrate.py`:
  - [ ] Function `narrate_trip(trip_meta: dict, day_skeleton: list[dict], cost_summary: dict, weather: dict, known_limitations: list[str]) -> dict`.
  - [ ] Build ONE prompt (per the structure discussed earlier: trip meta + fixed skeleton + cached descriptions + cost + weather + explicit "do not reorder / do not invent facts" instructions).
  - [ ] Call `llm/provider.py` ONCE.
  - [ ] Request structured JSON output matching: `{"overview": str, "days": [{"day": int, "narrative": str, "tip": str}], "general_tips": [str]}`.
  - [ ] Parse and validate the JSON (if parsing fails, retry once with a stricter "return ONLY valid JSON" instruction; if it fails twice, fall back to a plain-text template built from the skeleton data directly — no third LLM attempt).
- [ ] In `pipeline/`, locate wherever the current multi-pass generation happens (per the profiler output shared earlier: "Generate Plan", "Detailed Places: LLM Generation", "Realign Day Narrative" stages) and REPLACE all three with a single call to `narrate_trip()`.
- [ ] Add timing instrumentation around this call (reuse whatever profiling mechanism produced the earlier `Pipeline Profile` output) so you can directly compare before/after.

**Definition of done:** The pipeline profile shows one narration stage instead of three, and total narration time drops from hundreds of seconds to under ~30 seconds for a 4-day trip.

---

## PHASE 10 — LLM-judge validation pass (lightweight)

- [ ] Create `src/agentic_tour_planner/narration/validate.py`:
  - [ ] Function `validate_narration(narration: dict, day_skeleton: list[dict], cost_summary: dict) -> list[str]` (returns a list of detected issues, empty if none).
  - [ ] Check: does the grand total mentioned anywhere in the narration text roughly match `cost_summary["grand_total"]`? (simple regex/number extraction, not another LLM call, if feasible).
  - [ ] Check: does the narration mention any POI name NOT present in `day_skeleton`? (string containment check against the skeleton's POI names — flags hallucinated additions).
  - [ ] If issues are found, log them and regenerate ONLY the affected day's narrative section (not the whole trip) via a small targeted follow-up call.
- [ ] Wire this as a final step after Phase 9 in the pipeline.

**Definition of done:** Validation runs in under a couple seconds (mostly non-LLM string checks) and only triggers a regeneration for the specific day/section with a detected problem.

---

## PHASE 11 — Rewire existing surfaces (API, CLI, Streamlit UI)

- [ ] In `pipeline/`, replace the current end-to-end call chain with:
      `retrieval.pipeline.retrieve()` → `sequencing.bin_packer.sequence()` → `sequencing.cost.estimate_cost()` → `agents.graph` (critique loop) → `narration.narrate.narrate_trip()` → `narration.validate.validate_narration()`.
- [ ] Confirm the FINAL output shape returned by the pipeline still matches whatever `api/` and `app/streamlit_app.py` currently expect (check their existing parsing code) — if the shape changed, update the API response model and Streamlit rendering code to match, do not silently break the existing surfaces.
- [ ] Keep `POST /plans` SSE progress events working — emit a progress event after each phase completes (retrieval done → sequencing done → critique loop done → narration done) so the UI's existing progress bar still functions.
- [ ] Update `tour-planner-plan plan "Sikkim" --days 5 --origin "Kolkata"` CLI path to go through the same new pipeline.
- [ ] Re-run the existing test suite in `tests/` — fix any tests broken by the interface changes. Add new tests for each new module (`retrieval`, `sequencing`, `agents`, `narration`) with at least one test per public function.

**Definition of done:** All three surfaces (CLI, API, Streamlit UI) produce a full itinerary end-to-end through the new pipeline with no manual intervention, and existing tests pass (or are updated to reflect the new architecture).

---

## PHASE 12 — Final validation & profiling

- [ ] Run the same profiler used earlier (the one that produced the `Pipeline Profile (wall-clock)` output) against the new pipeline for the same Sikkim 4-day request.
- [ ] Confirm total wall-clock time is dramatically lower than the original ~745s baseline (target: well under 60s).
- [ ] Confirm output quality is at least as good: no hallucinated POIs, cost math matches, itinerary reads coherently.
- [ ] Write a short `CHANGELOG.md` entry summarizing what changed and the before/after profiling numbers — this becomes useful CV/portfolio evidence.

**Definition of done:** New pipeline profile committed alongside old one for comparison; itinerary quality manually spot-checked as good or better.

---

## Order-of-operations summary (for quick reference)

```
Phase 0  → environment
Phase 1  → Neo4j graph populated
Phase 2  → Chroma vector store populated
Phase 3  → deterministic retrieval works standalone
Phase 3B → dynamic per-destination interest tags replace static UI list
Phase 4  → deterministic sequencing works standalone
Phase 5  → deterministic cost works standalone
Phase 6  → LangGraph critique loop works standalone
Phase 7  → RAG reformulation upgrades Phase 3
Phase 8  → freshness agent plugs into retrieval
Phase 9  → single LLM narration replaces old 3-pass generation
Phase 10 → validation pass wraps narration
Phase 11 → wire all of the above into existing API/CLI/UI
Phase 12 → profile and confirm improvement
```

Do not begin a phase until the previous phase's "Definition of done" is checked off. Each phase should be its own commit / PR so problems can be isolated.
