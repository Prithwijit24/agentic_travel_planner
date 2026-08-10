# ✨ Agentic Travel Planner: Your Intelligent Trip Companion! ✨

Welcome to the **Agentic Travel Planner**! 🌍 This project brings you a production-oriented travel planning system designed to make your adventures seamless and smart.

---

## 🌟 Key Features & Capabilities:

-   **👷 Specialist Planning Workers:** Get expert guidance for crafting your route, managing your budget, and optimizing your trip timing.
-   **📝 Detailed Itineraries:** Per-day guidebook-style descriptions with opening hours, best times, transport, and (optional) place markers.
-   **🖼️ Destination Imagery:** Auto-resolved images per place with deterministic place-type search hints.
-   **⚡ Robust Runtime Surfaces:** Powered by **FastAPI** (with SSE progress + Prometheus metrics) for the backend and a stunning **Streamlit UI** for an interactive experience.
-   **🧠 Direct LLM Provider Layer:** Pluggable multi-provider routing with failover, per-provider timeouts, and cooldowns — no heavyweight frameworks.

---

## 🏗️ Architecture Overview:

Dive into the intelligent design powering your travel plans!

```text
User
  |
  v
UI / CLI (Your Interaction Hub!)
  - Streamlit UI (tour-planner-ui)
  - Interactive CLI (tour-planner-plan)
  |
  v
FastAPI (The Brains of the Operation!)
  - POST /plans            (async job + SSE progress stream)
  - GET /plans/{id}/images
  - POST /feedback
  - GET /metrics
  |
  v
Agentic Planning Layer (Orchestrating Intelligence!)
  - agentic pipeline (prompt builder + LLM calls)
  - LLM provider adapter (failover, cooldowns, per-provider timeouts)
  |
  v
Specialist Workers (Your Personal Travel Experts!)
  - route worker
  - budget worker
  - timing worker
  (LLM with deterministic heuristic fallback on schema violations)
  |
  v
Context Assembly (Gathering All the Info!)
  - AI Infra Stack (search / crawl / news)
  - DDGS live news fallback
  - weather tool
  - geonames search + geo day-clustering
  |
  v
Operations Store (Where History Resides!)
  - SQLite plan store (data/operations/plans.db)
```

---

## 📂 Key Modules: Where the Magic Happens!

Explore the core components that make this planner tick:

-   **`src/agentic_tour_planner/llm/provider.py`**: 🧠 Direct-httpx multi-provider LLM adapter with priority routing, failover, and per-provider timeouts.
-   **`src/agentic_tour_planner/services/planning_workers.py`**: 🤖 Specialist worker agents for routing, budgeting, and timing (LLM + heuristic fallback).
-   **`src/agentic_tour_planner/pipeline`**: 🚀 Orchestrates the planning workflow: prompts, geo day-clustering, travel constraints, and dedupe guards.
-   **`src/agentic_tour_planner/services/news_service.py`**: 📰 Live destination news with AI-stack + DDGS fallback and in-memory caching.
-   **`src/agentic_tour_planner/images`**: 🖼️ Image resolution pipeline (cache, sources, processors).
-   **`src/agentic_tour_planner/api`**: 🔗 FastAPI application with SSE events, Prometheus metrics, and SQLite persistence.

---

## 🚀 Runtime Surfaces: Get Started!

Interact with the Agentic Travel Planner using these powerful entry points:

-   `tour-planner-api` — FastAPI backend (`uvicorn`, port 8000)
-   `tour-planner-ui` — Streamlit UI
-   `tour-planner-plan` — interactive rich CLI (or `streamlit run src/agentic_tour_planner/app/streamlit_app.py`)

### 💻 CLI Commands (Examples):

```bash
# Interactive planning
tour-planner-plan interactive

# One-shot plan (rich output, saves to SQLite)
tour-planner-plan plan "Sikkim" --days 5 --origin "Kolkata"

# Live news about a destination
tour-planner-plan news --destination Sikkim

# Running the applications
tour-planner-api
tour-planner-ui
```

### 🌐 API Routes:

-   `GET /health`
-   `POST /plans` (async job)
-   `GET /plans`
-   `GET /plans/{plan_id}/images`
-   `GET /plans/stream/{request_id}` (SSE progress)
-   `POST /feedback`
-   `GET /metrics` (Prometheus)

---

## 🐳 Docker: Containerized Convenience!

Build and run your Agentic Travel Planner with Docker:

```bash
# Build the Docker image
docker build -t agentic-travel-planner:latest .

# Run the API container with environment variables from .env
docker run --rm -p 8000:8000 --env-file .env agentic-travel-planner:latest
```

**Relevant Files:**

-   [Dockerfile](Dockerfile)
-   [.dockerignore](.dockerignore)

---

## 💡 Development Notes & Fallbacks:

-   **LLM Failover:** Providers are tried in priority order (`oraclellm`, `agnes`, `nararouter`, `llm7io`, `opencode`); hung/busy providers are marked down with a cooldown and the next healthy provider serves the call.
-   **Worker Fallback:** When an LLM worker returns schema-violating JSON, deterministic heuristics generate the route/budget/timing guidance.
-   **Deterministic Guards:** Detailed places are deduplicated (same-day and cross-day, ignoring `(optional)` markers and markdown) and day themes/summaries are realigned after geo-clustering.
-   **Data Storage:** SQLite stores your saved plan history within `data/operations/plans.db`.

---

## 🚀 Quick Start:

Ready to jump in? Check out the detailed setup and usage instructions in our [**QUICKSTART.md**](QUICKSTART.md) guide!

---

## 🔄 v2 Hybrid Graph/Vector RAG Restructure (2026-08-11)

The planning core has been upgraded from an LLM-heavy multi-pass pipeline (~745s) to a hybrid graph/vector RAG system with deterministic retrieval/sequencing and a real multi-agent critique loop (~13-35s).

### New Architecture

```
User Request (destination, interests, days, budget_tier, travelers)
    → retrieval.pipeline.retrieve()          [graph candidates → vector filter → enrich]
    → sequencing.bin_packer.sequence()       [deterministic day assignment]
    → agents.graph (LangGraph critique loop)  [cost → budget critique → timing critique → revise]
    → narration.narrate.narrate_trip()        [single LLM pass]
    → narration.validate.validate_narration() [hallucination + cost checks]
    → PlanningResponse (same shape as before)
```

### New Packages

| Package | Purpose | Key Files |
|---------|---------|-----------|
| `graphdb/` | Neo4j ingestion + client | `client.py`, `parse_dump.py`, `infer_hierarchy.py`, `load_neo4j.py` |
| `vectordb/` | ChromaDB client + embedding | `client.py`, `embed_pois.py` |
| `retrieval/` | Unified retrieval with fallback | `graph_retrieval.py`, `vector_retrieval.py`, `api_retrieval.py`, `pipeline.py` |
| `sequencing/` | Deterministic bin-packing | `bin_packer.py` |
| `agents/` | Cost agent + LangGraph critique loop | `state.py`, `cost_agent.py`, `budget_agent.py`, `timing_agent.py`, `planner_agent.py`, `graph.py`, `retrieval_agent.py`, `freshness_agent.py` |
| `narration/` | Single-pass LLM narration + validation | `narrate.py`, `validate.py` |
| `pipeline/` | Orchestrator | `v2_orchestrator.py`, `agentic_pipeline.py` (adapter) |

---

## 📋 Complete Script Execution Guide

### Prerequisites

```bash
# Neo4j (Docker)
docker ps | grep neo4j || docker start neo4j-test

# Verify Python environment
cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner
python -c "import agentic_tour_planner; print('Import OK')"
```

---

### Phase 1: Infrastructure Verification

```bash
# 1.1 Check Neo4j connection
python -c "from agentic_tour_planner.graphdb.client import get_graph_db; c = get_graph_db(); print('Neo4j OK:', c.run_query('RETURN 1 AS t'))"

# 1.2 Check ChromaDB
python -c "from agentic_tour_planner.vectordb.client import get_vector_db; v = get_vector_db(); print('Chroma OK:', v.count(), 'POIs')"

# 1.3 Check LLM providers
python -c "from agentic_tour_planner.llm.provider import LLMProvider; p = LLMProvider(); print('LLMs:', p.list_providers())"

# 1.4 Check config
python -c "from agentic_tour_planner.config.settings import get_settings; print('Config OK:', get_settings().app_env)"
```

---

### Phase 2: Component Tests (No API Keys)

```bash
# 2.1 Test retrieval (Neo4j + ChromaDB)
python scripts/test_retrieval.py

# 2.2 Test sequencing (bin-packing algorithm)
python scripts/test_sequencing.py
```

---

### Phase 3: Pipeline Tests (Needs LLM API Keys)

```bash
# 3.1 Test LLM provider connectivity
python scripts/test_all_providers.py

# 3.2 Test critique loop (LangGraph)
python scripts/test_critique_loop.py

# 3.3 Test full E2E pipeline
python scripts/test_e2e_pipeline.py
```

---

### Phase 4: CLI Testing

```bash
# 4.1 Basic plan generation
python -m agentic_tour_planner.cli.plan plan \
  --destination "Gangtok" --days 4 \
  --interests "monasteries,food,nature" \
  --budget midrange --members 4 --month "August"

# 4.2 Save to file
python -m agentic_tour_planner.cli.plan plan \
  --destination "Gangtok" --days 3 \
  --interests "monasteries" --budget midrange --members 2 \
  --output gangtok_plan.json

# 4.3 Interactive mode
python -m agentic_tour_planner.cli.plan interactive
```

**CLI Options:**
| Flag | Description | Default |
|------|-------------|---------|
| `--destination, -d` | Travel destination | (required) |
| `--days, -n` | Number of trip days | 4 |
| `--interests, -i` | Comma-separated interests | "landmarks,food,walks" |
| `--budget, -b` | Budget level (budget/midrange/luxury) | "midrange" |
| `--month, -m` | Travel month | "June" |
| `--members` | Number of travellers | 1 |
| `--provider, -p` | LLM provider override | (from config) |
| `--output, -f` | Output file for JSON result | (none) |
| `--origin` | Origin city | (none) |
| `--places-per-day` | Places per day range | "3-5" |
| `--transport` | Transport mode | (none) |
| `--live` | Include live web data | False |

---

### Phase 5: API Server Testing

```bash
# 5.1 Start API server (background)
python -m agentic_tour_planner.api.main &
# OR use the entry point: tour-planner-api

# 5.2 Health check
curl http://127.0.0.1:8000/health

# 5.3 Get dynamic interests for a destination
curl http://127.0.0.1:8000/destinations/Gangtok/interests

# 5.4 Submit plan request
curl -X POST http://127.0.0.1:8000/plans \
  -H "Content-Type: application/json" \
  -d '{"destination":"Gangtok","trip_length_days":4,"interests":["monasteries","food"],"travelers":2}'

# 5.5 Stream results (use request_id from 5.4)
curl http://127.0.0.1:8000/plans/stream/<request_id>

# 5.6 List saved plans
curl http://127.0.0.1:8000/plans

# 5.7 Get plan images
curl http://127.0.0.1:8000/plans/<plan_id>/images
```

**API Endpoints:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/plans` | Submit plan job (async) |
| GET | `/plans` | List saved plans |
| GET | `/plans/stream/{request_id}` | SSE progress stream |
| GET | `/plans/{plan_id}/images` | Get plan images |
| GET | `/destinations/{name}/interests` | Dynamic interest tags |
| POST | `/feedback` | Submit plan feedback |
| GET | `/metrics` | Prometheus metrics |

---

### Phase 6: UI Testing

```bash
# 6.1 Start Streamlit UI (background)
python -m streamlit run src/agentic_tour_planner/app/streamlit_app.py \
  --server.port 8501 --server.headless true &
# OR: tour-planner-ui

# 6.2 Open browser: http://localhost:8501
```

---

### Phase 7: Unit Tests

```bash
# 7.1 All unit tests
python -m pytest tests/unit/ -v

# 7.2 Quick summary
python -m pytest tests/unit/ -q

# 7.3 Specific test file
python -m pytest tests/unit/test_pipeline.py -v

# 7.4 Tests by keyword
python -m pytest tests/unit/ -k "test_sequence" -v

# 7.5 Exclude integration tests
python -m pytest tests/unit/ -m "not integration" -v
```

**Unit Test Files:**
| Test | What it tests |
|------|--------------|
| `test_ai_stack_client.py` | AI Infra Stack API client |
| `test_api_client.py` | HTTP API client |
| `test_api_images.py` | Image API endpoints |
| `test_api_main.py` | FastAPI main endpoints |
| `test_api_streaming.py` | SSE streaming |
| `test_cost_estimator.py` | Cost estimation |
| `test_day_clustering.py` | Geographic clustering |
| `test_events.py` | EventEmitter |
| `test_image_*.py` | Image pipeline (cache, models, sources, etc.) |
| `test_llm_provider.py` | LLM provider fallback |
| `test_map_tool.py` | Map rendering |
| `test_models.py` | Domain models |
| `test_output_builder.py` | Output formatting |
| `test_pipeline.py` | Pipeline orchestration |
| `test_planning_workers.py` | Planning workers |
| `test_store.py` | SQLite storage |
| `test_streamlit_app.py` | Streamlit UI |
| `test_travel_constraints.py` | Travel constraints |

---

### Phase 8: Integration Tests (Needs Live API Keys)

```bash
# 8.1 All integration tests
python -m pytest tests/integration/ -v

# 8.2 Specific test
python -m pytest tests/integration/test_api.py -v

# 8.3 With markers
python -m pytest tests/ -m "integration" -v
```

**Integration Test Files:**
| Test | What it tests | Needs live API? |
|------|--------------|-----------------|
| `test_ai_stack_real.py` | Real AI Infra Stack calls | Yes |
| `test_api.py` | Full API end-to-end | Yes |
| `test_image_pipeline_e2e.py` | Image pipeline E2E | Yes |
| `test_llm_walltime.py` | LLM wall-clock timing | Yes |

---

### Phase 9: Neo4j Data Ingestion (Standalone)

```bash
# 9.1 Parse Wikivoyage XML dump → JSONL
python -m agentic_tour_planner.graphdb.parse_dump enwikivoyage-latest-pages-articles.xml

# 9.2 Infer Country/Region/City hierarchy
python -m agentic_tour_planner.graphdb.infer_hierarchy

# 9.3 Load everything into Neo4j
python -m agentic_tour_planner.graphdb.load_neo4j

# 9.4 Embed POI descriptions into ChromaDB
python -m agentic_tour_planner.vectordb.embed_pois
```

---

### Phase 10: Graphify (Codebase Knowledge Graph)

```bash
# Build knowledge graph from codebase
graphify .

# Query the graph
graphify query "How does retrieval work?"

# Export interactive HTML
graphify export html
```

---

## 🌐 Service URLs

| Service | URL | Start Command |
|---------|-----|---------------|
| API | http://127.0.0.1:8000 | `python -m agentic_tour_planner.api.main` |
| API Docs | http://127.0.0.1:8000/docs | (auto-generated Swagger) |
| UI | http://localhost:8501 | `python -m streamlit run src/agentic_tour_planner/app/streamlit_app.py --server.port 8501` |
| Neo4j Browser | http://localhost:7474 | `docker start neo4j-test` |

---

## 🔧 Configuration

Configuration is loaded from YAML files in `src/agentic_tour_planner/config/`:
- `general.yml` — app settings, Neo4j, ChromaDB, feature flags
- `llm.yml` — LLM provider configs
- `api.yml` — API settings
- `storage.yml` — storage paths

Environment variables override YAML values (see `.env` for API keys).

**Key Config Values:**
```yaml
# Neo4j
neo4j_uri: "bolt://localhost:7687"
neo4j_user: "neo4j"
neo4j_password: "changeme"

# ChromaDB
chroma_persist_dir: "src/agentic_tour_planner/data/chroma"

# Feature flags
use_graph_db: true
use_rag_reformulation: false
```

---

## 📊 Performance

| Metric | v1 (Old) | v2 (New) |
|--------|----------|----------|
| Wall time | ~745s | ~13-35s |
| LLM calls | 3 (sequential) | 2-4 (with critique loop) |
| Data source | LLM-generated | Neo4j + ChromaDB (real POIs) |
| Hallucination risk | High | Low (fixed skeleton + validation) |
| Determinism | Non-deterministic | Deterministic retrieval/sequencing |

---

## 📝 Recent Changes (v2 Restructure)

- **Neo4j graph DB** for structured POI data (Wikivoyage)
- **ChromaDB vector store** for semantic interest-based retrieval
- **Deterministic bin-packing** for day assignment
- **LangGraph critique loop** for budget/timing validation
- **Single-pass LLM narration** replacing 3-pass generation
- **Non-LLM validation** for hallucination detection
- **Dynamic interest tags** from real data
- **Graceful API fallback** when Neo4j/Chroma unavailable

