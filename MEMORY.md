# MEMORY.md — Hybrid Graph/Vector RAG Restructure

## Current Phase: 1 (Wikivoyage → Neo4j Ingestion)
## Last Updated: 2026-08-10

## Spec Location
`docs/superpowers/specs/2026-08-10-hybrid-graph-vector-rag-restructure-design.md`

## Ingestion Scripts Source
`/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/src/agentic_tour_planner/instructions_and_next_step_implementations/`
- `1_parse_dump.py` → will become `graphdb/parse_dump.py`
- `2_infer_hierarchy.py` → will become `graphdb/infer_hierarchy.py`
- `3_load_neo4j.py` → will become `graphdb/load_neo4j.py`
- `requirements.txt` → mwparserfromhell, neo4j

## Decisions Made
- **Retrieval:** Strategy pattern with per-step fallback (graph+vector primary, API fallback)
- **Pipeline:** Direct replacement (no feature flag, no parallel old+new)
- **Agents:** LangGraph with TypedDict state, bounded 2-iteration critique loop
- **Cost:** LLM classifies cost types (per_person/per_room/flat) + arithmetic
- **Narration:** Single LLM pass + non-LLM validation + targeted regeneration
- **Cutover:** Delete old pipeline, wire new one to existing API/CLI/UI
- **Tests:** Phase-by-phase rewrite, old tests for replaced code deleted
- **Ingestion:** In-package from day one (graphdb/ subpackage)

## Phase Checklist

### Phase 0 — Environment setup [DONE]
- [x] Install Neo4j (Docker, already running as neo4j-test, password=changeme)
- [x] Install ChromaDB (already installed)
- [x] Add deps (mwparserfromhell installed; neo4j, chromadb, langgraph already present)
- [x] Create empty package folders: graphdb/, vectordb/, retrieval/, sequencing/, agents/, narration/
- [x] Add NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, CHROMA_PERSIST_DIR to config

### Phase 1 — Wikivoyage → Neo4j ingestion [IN PROGRESS]
- [ ] Create graphdb/parse_dump.py from 1_parse_dump.py
- [ ] Create graphdb/infer_hierarchy.py from 2_infer_hierarchy.py
- [ ] Create graphdb/load_neo4j.py from 3_load_neo4j.py (use config loader, not os.environ)
- [ ] Create graphdb/client.py (GraphDBClient wrapper)
- [ ] Small test slice (Sikkim + 2-3 pages)
- [ ] Run parse → infer → load on small slice
- [ ] Verify in Neo4j browser
- [ ] Add post_clean() helper
- [ ] Spot-check long_description values
- [ ] Full dump run (after small slice works)

### Phase 2 — Chroma vector store [PENDING]
- [ ] Create vectordb/client.py (VectorDBClient)
- [ ] Create vectordb/embed_pois.py
- [ ] Run on small test slice
- [ ] Sanity test query
- [ ] Run on full POI set

### Phase 3 — Deterministic retrieval [PENDING]
- [ ] Create retrieval/graph_retrieval.py
- [ ] Create retrieval/vector_retrieval.py
- [ ] Create retrieval/pipeline.py
- [ ] Create scripts/test_retrieval.py
- [ ] Verify <1s, correct results

### Phase 3B — Dynamic interest tags [PENDING]
- [ ] Add get_available_tags() to graph_retrieval.py
- [ ] Add GET /destinations/{name}/interests endpoint
- [ ] Update Streamlit UI for dynamic tags
- [ ] Make Interests optional
- [ ] Add get_balanced_default_pois()
- [ ] Wire into retrieve() pipeline

### Phase 4 — Deterministic sequencing [PENDING]
- [ ] Create sequencing/bin_packer.py
- [ ] Create scripts/test_sequencing.py
- [ ] Verify determinism (same input → same output)

### Phase 5 — Cost agent [PENDING]
- [ ] Create agents/cost_agent.py
- [ ] LLM classification of cost types (per_person/per_room/flat)
- [ ] Arithmetic application
- [ ] Test with Phase 4 output

### Phase 6 — LangGraph critique loop [PENDING]
- [ ] Create agents/state.py (TripState TypedDict)
- [ ] Create agents/budget_agent.py
- [ ] Create agents/timing_agent.py
- [ ] Create agents/planner_agent.py
- [ ] Create agents/graph.py (LangGraph wiring)
- [ ] Create scripts/test_critique_loop.py
- [ ] Verify termination + constraint response

### Phase 7 — RAG query reformulation [PENDING]
- [ ] Create agents/retrieval_agent.py
- [ ] Wire into retrieval/pipeline.py behind USE_RAG_REFORMULATION flag
- [ ] A/B test vs Phase 3

### Phase 8 — Freshness agent [PENDING]
- [ ] Create agents/freshness_agent.py
- [ ] Wire into retrieval/pipeline.py
- [ ] Test stale POI backfill + persist

### Phase 9 — Single-pass narration [PENDING]
- [ ] Create narration/narrate.py
- [ ] Replace 3-pass generation with single narrate_trip() call
- [ ] Add timing instrumentation

### Phase 10 — Validation pass [PENDING]
- [ ] Create narration/validate.py
- [ ] Wire as final step after narration

### Phase 11 — Rewire API/CLI/UI [PENDING]
- [ ] Replace pipeline/ with new orchestrator
- [ ] Confirm output shape unchanged
- [ ] Keep SSE progress events working
- [ ] Update CLI path
- [ ] Rewrite broken tests

### Phase 12 — Final validation & profiling [PENDING]
- [ ] Profile both old and new (commit both)
- [ ] Confirm <60s target
- [ ] Confirm output quality
- [ ] Write CHANGELOG.md entry

## Key Architecture Notes
- Backend fallback: Neo4j/Chroma down → AI Infra Stack API
- Cost: LLM classifies, arithmetic multiplies (not generic)
- Critique loop: budget_agent + timing_agent + planner_agent, max 2 revisions
- Narration: 1 LLM call, retry once, template fallback
- No feature flag — direct replacement of old pipeline

## Conventions
- Python 3.11+, src layout, hatch build
- Ruff linter+formatter (line-length 120)
- Pydantic v2 models
- loguru for logging
- Existing llm/provider.py reused as-is
- Conventional commits enforced (docs:, feat:, fix:, refactor:, chore:, test:)
