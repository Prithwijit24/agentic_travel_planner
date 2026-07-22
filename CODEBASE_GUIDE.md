# 🗺️ Agentic Travel Planner — Complete Codebase Guide

> **A production-ready, AI-powered travel planning system** built with FastAPI, LangGraph, RAG retrieval, and a pluggable LLM provider layer.

---

## 📋 Table of Contents

- [🏗️ Overall Architecture](#️-overall-architecture)
- [📦 Module-by-Module Deep Dive](#-module-by-module-deep-dive)
- [🧭 Navigation Guide — Where to Start](#-navigation-guide--where-to-start)
- [🔀 Request Flow — End to End](#-request-flow--end-to-end)
- [🛠️ How to Extend & Modify](#️-how-to-extend--modify)
- [🚀 Running the Project](#-running-the-project)
- [📁 File Index](#-file-index)

---

## 🏗️ Overall Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        🖥️  STREAMLIT UI                             │
│              src/agentic_tour_planner/app/streamlit_app.py          │
│         (User fills form → POSTs to FastAPI → renders response)     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP POST /plans
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        🔌  FASTAPI API                              │
│              src/agentic_tour_planner/api/main.py                   │
│   Routes: /health, /plans, /sources, /feedback, /metrics            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     🧠  PLANNER SERVICE                             │
│            src/agentic_tour_planner/services/planner.py             │
│         (Orchestrates pipeline + persists to SQLite)                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  🔄  AGENTIC PIPELINE (LangGraph)                   │
│       src/agentic_tour_planner/pipeline/agentic_pipeline.py         │
│                                                                     │
│   ┌─────────────┐   ┌──────────────┐   ┌───────────┐   ┌─────────┐│
│   │ gather_ctx  │──▶│build_insights│──▶│build_prompt│──▶│gen_plan ││
│   └──────┬──────┘   └──────────────┘   └───────────┘   └────┬────┘│
│          │                                                   │      │
│          ▼                                                   ▼      │
│   ┌─────────────────────────────────┐  ┌──────────────────────┐    │
│   │  📚 RETRIEVAL LAYER             │  │  🤖 LLM PROVIDER     │    │
│   │  • VectorStore (ChromaDB)       │  │  • OpenAI / Google   │    │
│   │  • HybridReranker               │  │  • Ollama / OpenRouter│   │
│   │  • WebSearchTool (DuckDuckGo)   │  │  • XAI               │    │
│   │  • PlaceIntelTool (Google Maps) │  └──────────────────────┘    │
│   │  • WeatherTool (OpenWeather)    │                              │
│   └─────────────────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│  📥 INGESTION     │  │  💾 STORAGE      │  │  📊 OBSERVABILITY    │
│  • WebCrawler     │  │  • SQLitePlan    │  │  • Prometheus        │
│  • Connectors     │  │    Store         │  │  • LangSmith         │
│  • Manifest       │  │  • SQLiteIngest  │  │  • Metrics Export    │
│  • CLI Commands   │  │    ion Store     │  │                    │
└──────────────────┘  └──────────────────┘  └──────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐
│  🔧 TOOLS         │  │  ⚙️  CONFIG      │  │  🧪 EVALUATION       │
│  • WebSearch      │  │  • Settings      │  │  • RAGAS Pipeline    │
│  • PlaceIntel     │  │  • .env loading  │  │  • CLI Commands      │
│  • Weather        │  │  • All params    │  │                    │
└──────────────────┘  └──────────────────┘  └──────────────────────┘
```

### 🧱 Architectural Layers

| Layer | Purpose | Key Files |
|-------|---------|-----------|
| **🎨 UI** | Streamlit web interface for users | `app/streamlit_app.py` |
| **🔌 API** | FastAPI REST endpoints | `api/main.py` |
| **🧠 Service** | Business logic orchestration | `services/planner.py` |
| **🔄 Pipeline** | LangGraph state machine for planning | `pipeline/agentic_pipeline.py`, `pipeline/graph.py` |
| **📚 Retrieval** | RAG: vector store, reranking, tools | `retrieval/`, `tools/` |
| **🤖 LLM** | Multi-provider LLM abstraction | `llm/provider.py` |
| **📥 Ingestion** | Knowledge base population | `ingestion/` |
| **💾 Storage** | SQLite persistence | `storage/` |
| **📊 Observability** | Metrics & tracing | `observability/` |
| **🧪 Evaluation** | RAGAS quality measurement | `evaluation/` |
| **⚙️ Config** | Settings & environment | `config/settings.py` |
| **🏗️ Domain** | Pydantic data models | `domain/models.py` |

---

## 📦 Module-by-Module Deep Dive

### 🏗️ Domain Models — `domain/models.py`

**📍 File:** `src/agentic_tour_planner/domain/models.py` (206 lines)

**🎯 Purpose:** Defines every data structure used across the entire system. This is the **single source of truth** for all types.

**📊 Key Models:**

| Model | Purpose | Used By |
|-------|---------|---------|
| `PlanningRequest` | User input: destination, interests, budget, dates | UI, API, Pipeline |
| `PlanningResponse` | Generated itinerary with day plans, citations, insights | Pipeline, API, UI |
| `DayPlan` | Single day: morning/afternoon/evening/meal activities | Response |
| `SourceDocument` | Ingested content chunk with metadata | Retrieval, Ingestion |
| `RetrievedContext` | Aggregated evidence: docs + search + hours + weather | Pipeline |
| `PlanningInsights` | Route + Budget + Timing guidance | Pipeline, Prompts |
| `StoredPlanRecord` | Persisted plan in SQLite | Storage, API |
| `SourceSeed` | URL to ingest with metadata | Ingestion |
| `SourceManifest` | Batch ingestion config with defaults | Ingestion CLI |
| `IngestedSourceRecord` | Track of what was ingested | Ingestion Store |
| `IngestionRunRecord` | Stats for a batch ingestion run | Ingestion Store |

**🔑 Type Aliases:**
```python
ProviderName = Literal["openai", "google", "ollama", "openrouter", "xai"]
BudgetLevel = Literal["budget", "midrange", "luxury"]
SourceKind = Literal["wikivoyage", "web", "youtube", "file", "search"]
CrawlBackend = Literal["httpx", "trafilatura", "crawl4ai", "scrapling"]
```

**💡 Tip:** Any time you need to change data shapes, start here. All other modules import from this file.

---

### ⚙️ Configuration — `config/settings.py`

**📍 File:** `src/agentic_tour_planner/config/settings.py` (83 lines)

**🎯 Purpose:** Centralized settings loaded from `.env` file via `pydantic-settings`.

**📊 Setting Categories:**

| Category | Key Settings | Default |
|----------|-------------|---------|
| **App** | `app_env`, `app_name`, `log_level` | development |
| **LangSmith** | `langsmith_tracing`, `langsmith_api_key` | disabled |
| **LLM** | `default_llm_provider`, `default_llm_model` | openai / gpt-4o-mini |
| **API Keys** | `openai_api_key`, `google_api_key`, `tavily_api_key`, etc. | None |
| **Paths** | `vector_store_dir`, `operations_db_path` | data/ |
| **Retrieval** | `retrieval_top_k`, `rerank_top_k`, `chunk_size` | 8 / 4 / 850 |
| **Crawl** | `web_crawl_backend`, `crawl_max_concurrency` | trafilatura / 4 |
| **Redis** | `redis_url`, `redis_cache_enabled`, `redis_cache_ttl_seconds` | disabled |
| **Embedding** | `embedding_model_name`, `collection_name` | BAAI/bge-small-en-v1.5 |

**🔑 Access Pattern:**
```python
from agentic_tour_planner.config.settings import get_settings
settings = get_settings()  # Singleton via @lru_cache
```

**💡 Tip:** Add new env vars here. The `.env` file is auto-loaded. Settings also auto-create directories on first access.

---

### 🔄 Pipeline — `pipeline/`

#### `pipeline/agentic_pipeline.py` (73 lines)

**🎯 Purpose:** Main orchestrator. Wires together all components into a runnable pipeline.

**📊 Class: `AgenticTourPlannerPipeline`**

```
__init__()
  ├── LLMProvider()              # Multi-provider LLM
  ├── VectorStore()              # ChromaDB vector store
  ├── HybridReranker()           # Lexical + semantic reranking
  ├── WebSearchTool()            # DuckDuckGo search
  ├── PlaceIntelTool()           # Google Maps / search fallback
  ├── WeatherTool()              # OpenWeatherMap
  ├── PlanningInsightsBuilder()  # Route + Budget + Timing
  └── build_planner_graph()      # LangGraph state machine

gather_context(request)          # Async: retrieve + search + weather
run(request)                     # Async: invoke graph → build response
```

**🔀 Flow:**
1. `gather_context()` — queries vector store, reranks, searches web, looks up hours & weather
2. `graph.ainvoke()` — runs the LangGraph state machine
3. Builds `PlanningResponse` from graph output + context

#### `pipeline/graph.py` (50 lines)

**🎯 Purpose:** LangGraph state machine definition.

**📊 State (`PlannerGraphState`):**
```python
{
    "request": PlanningRequest,
    "context": RetrievedContext,
    "insights": PlanningInsights,
    "prompt": str,
    "plan_json": dict,
}
```

**🔀 Node Flow:**
```
gather_context → build_insights → build_prompt → generate_plan → END
```

Each node is an async function that returns a partial state update.

#### `pipeline/prompts.py` (65 lines)

**🎯 Purpose:** Builds the LLM prompt from request + context + insights.

**📊 `build_itinerary_prompt()`** assembles:
- User input (destination, interests, budget, notes)
- Route/budget/timing guidance from workers
- Evidence blocks from documents, search results, place hours, weather
- JSON schema instructions for the LLM

---

### 🤖 LLM Provider — `llm/provider.py` (126 lines)

**🎯 Purpose:** Abstracts multiple LLM backends behind a single interface.

**📊 Class: `LLMProvider`**

| Method | Purpose |
|--------|---------|
| `resolve_provider()` | Picks provider/model from request or settings |
| `_build_chat_model()` | Creates LangChain chat model for the provider |
| `complete_json()` | Async: sends prompt, parses JSON response (with retry) |
| `_fallback_json()` | Generates a basic plan without LLM if all providers fail |

**🔌 Supported Providers:**
- **OpenAI** — via `ChatOpenAI`
- **Google** — via `ChatGoogleGenerativeAI`
- **Ollama** — via `ChatOllama` (local)
- **OpenRouter** — via `ChatOpenAI` with custom base_url
- **XAI** — via `ChatOpenAI` with x.ai base_url

**💡 Tip:** All providers use `tenacity` for automatic retries (3 attempts, exponential backoff).

---

### 📚 Retrieval — `retrieval/`

#### `retrieval/vector_store.py` (116 lines)

**🎯 Purpose:** ChromaDB vector store with fallback to in-memory keyword search.

**📊 Class: `VectorStore`**

| Method | Purpose |
|--------|---------|
| `upsert_documents()` | Chunks documents, embeds, stores in ChromaDB |
| `retrieve()` | Embeds query, searches ChromaDB, returns top-k documents |
| `delete_source()` | Removes all chunks from a source |

**🔄 Fallback:** If ChromaDB/FastEmbed aren't installed, falls back to simple keyword overlap scoring.

#### `retrieval/chunker.py` (19 lines)

**🎯 Purpose:** Simple text chunking with overlap.

```python
chunk_text(text, chunk_size=850, overlap=120) → Iterable[str]
```

#### `retrieval/reranker.py` (32 lines)

**🎯 Purpose:** Hybrid reranker combining lexical overlap + vector similarity scores.

**📊 Class: `HybridReranker`**
- Uses `Counter`-based token overlap for lexical scoring
- Adds vector store distance score
- Sorts by combined score, returns top-k

---

### 🔧 Tools — `tools/`

#### `tools/web_search.py` (26 lines)

**🎯 Purpose:** DuckDuckGo search wrapper.

| Method | Purpose |
|--------|---------|
| `search()` | General text search → `SearchResult` list |
| `suggest_places()` | Search for places at a destination |
| `search_opening_hours()` | Search for venue opening hours |

#### `tools/place_intel.py` (54 lines)

**🎯 Purpose:** Look up venue opening hours.

**🔀 Strategy:**
1. Try Google Maps API first (if key configured)
2. Fall back to DuckDuckGo search

#### `tools/weather.py` (30 lines)

**🎯 Purpose:** Get current weather via OpenWeatherMap API.

Returns `WeatherSnapshot` with temperature, humidity, wind, description.

---

### 📥 Ingestion — `ingestion/`

#### `ingestion/service.py` (169 lines)

**🎯 Purpose:** Orchestrates knowledge base ingestion from various sources.

**📊 Class: `IngestionService`**

| Method | Purpose |
|--------|---------|
| `ingest_seed()` | Fetch + chunk + embed + persist a single source |
| `ingest_manifest()` | Batch ingest from a JSON manifest file |
| `ingest_wikivoyage()` | Quick ingest a Wikivoyage article |
| `ingest_web()` | Quick ingest a web URL |
| `ingest_youtube()` | Quick ingest a YouTube transcript |
| `ingest_file()` | Quick ingest a local file |
| `list_sources()` | List all ingested sources |

**🔀 Ingestion Flow:**
```
SourceSeed → SourceConnectors.fetch() → SourceDocument
           → VectorStore.upsert() → SQLiteIngestionStore.upsert()
           → IngestedSourceRecord
```

**⚡ Concurrency:** Uses `asyncio.Semaphore` for controlled parallel crawling.

#### `ingestion/connectors.py` (90 lines)

**🎯 Purpose:** Fetch content from different source types.

| Method | Source | Returns |
|--------|--------|---------|
| `fetch_wikivoyage()` | Wikivoyage wiki pages | `SourceDocument` |
| `fetch_web_document()` | Any web URL (via crawler) | `SourceDocument` |
| `fetch_youtube_transcript()` | YouTube videos | `SourceDocument` |
| `fetch_file_document()` | Local files | `SourceDocument` |

#### `ingestion/crawler.py` (170 lines)

**🎯 Purpose:** Web crawling with multiple backends and proxy support.

**📊 Class: `WebCrawler`**

| Backend | Description |
|---------|-------------|
| `trafilatura` | Default — fast, clean text extraction |
| `httpx` | Raw HTTP with proxy support |
| `crawl4ai` | Full browser rendering (optional) |
| `scrapling` | Advanced scraping (optional) |

**📊 Class: `ProxyRouter`**
- `direct` — no proxy
- `round_robin` — cycle through proxy list
- `hash` — consistent proxy per URL

**💾 Caching:** Results cached in Redis (if enabled) with configurable TTL.

#### `ingestion/manifest.py` (31 lines)

**🎯 Purpose:** Load and normalize source manifest JSON files.

Handles legacy field names (`kind` → `source_type`, `identifier` → `destination`).

#### `ingestion/cli.py` (41 lines)

**🎯 Purpose:** CLI commands via Typer.

```bash
tour-planner-ingest wikivoyage "Paris"
tour-planner-ingest web "https://example.com"
tour-planner-ingest youtube "https://youtube.com/watch?v=..."
tour-planner-ingest file "./notes.txt"
tour-planner-ingest manifest "./manifest.json" --force
tour-planner-ingest sources --limit 20
```

---

### 💾 Storage — `storage/`

#### `storage/sqlite_store.py` (126 lines)

**🎯 Purpose:** Persist plans and feedback to SQLite.

**📊 Class: `SQLitePlanStore`**

| Method | Purpose |
|--------|---------|
| `save_plan()` | Store a generated plan (request + response as JSON) |
| `list_plans()` | Retrieve recent plans |
| `save_feedback()` | Store user feedback for a plan |

**📊 Tables:**
- `plans` — plan_id, destination, request_json, response_json, provider, model
- `plan_feedback` — plan_id, rating, comments, created_at

#### `storage/ingestion_store.py` (260 lines)

**🎯 Purpose:** Track ingested sources and ingestion runs.

**📊 Class: `SQLiteIngestionStore`**

| Method | Purpose |
|--------|---------|
| `upsert_source()` | Insert or update an ingested source record |
| `get_source()` | Look up a source by key |
| `should_refresh()` | Check if a source needs re-ingestion based on age |
| `start_run()` / `finish_run()` | Track batch ingestion runs |
| `list_sources()` | List all ingested sources |
| `source_key()` | Generate a unique key from a seed |

**📊 Tables:**
- `ingested_sources` — source tracking with content hash, chunk count, tags
- `ingestion_runs` — batch run statistics

---

### 🧠 Services — `services/`

#### `services/planner.py` (17 lines)

**🎯 Purpose:** Thin service layer between API and pipeline.

```python
PlannerService.create_plan(request)
  → pipeline.run(request)
  → store.save_plan(request, response)
  → return response
```

#### `services/planning_workers.py` (94 lines)

**🎯 Purpose:** Generate planning insights (route, budget, timing) without LLM.

| Worker | Output | Logic |
|--------|--------|-------|
| `RoutePlannerWorker` | `RouteGuidance` | Cluster advice from documents, transit tips |
| `BudgetPlannerWorker` | `BudgetGuidance` | Fixed daily rates by budget level × interest multiplier |
| `TimingPlannerWorker` | `TimingGuidance` | Season detection, booking windows |
| `PlanningInsightsBuilder` | `PlanningInsights` | Combines all three workers |

**💡 Tip:** These are deterministic — no LLM calls, no network. Fast and reliable.

---

### 📊 Observability — `observability/`

#### `observability/metrics.py` (19 lines)

**🎯 Purpose:** Prometheus metrics for the API.

```python
REQUEST_COUNT  # Counter: tour_planner_requests_total{endpoint, provider}
REQUEST_LATENCY # Histogram: tour_planner_request_latency_seconds{endpoint}
export_metrics()  # → /metrics endpoint
```

#### `observability/langsmith.py` (16 lines)

**🎯 Purpose:** Configure LangSmith tracing for LLM calls.

Sets environment variables when `langsmith_api_key` is configured.

---

### 🧪 Evaluation — `evaluation/`

#### `evaluation/ragas_pipeline.py` (101 lines)

**🎯 Purpose:** RAGAS evaluation pipeline for measuring RAG quality.

**📊 Class: `RagasEvaluationPipeline`**

| Method | Purpose |
|--------|---------|
| `load_cases()` | Load evaluation cases from JSON |
| `build_dataset_rows()` | Run pipeline on cases, build RAGAS dataset |
| `export_dataset()` | Export dataset for external evaluation |
| `run_ragas()` | Run full RAGAS evaluation with metrics |

**📊 Metrics:** answer_relevancy, faithfulness, context_recall

#### `evaluation/cli.py` (22 lines)

```bash
tour-planner-eval export "./cases.json" --output-path "./dataset.json"
tour-planner-eval ragas "./cases.json" --output-path "./report.json"
```

---

### 🎨 UI — `app/streamlit_app.py` (228 lines)

**🎯 Purpose:** Streamlit web interface.

**📊 Three Tabs:**
1. **Plan Trip** — Form with destination, interests, budget → generates plan via API
2. **Recent Plans** — Browse stored plans from SQLite
3. **Knowledge Sources** — View ingested sources

**🔀 Flow:**
```
User fills form → PlanningRequest → POST /plans → render response
```

**📊 Sidebar Controls:**
- LLM provider & model selection
- Trip length slider
- Budget level selector
- Live data toggle
- Attractions per day slider

---

### 🔌 API — `api/main.py` (68 lines)

**🎯 Purpose:** FastAPI REST API.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check with env info |
| `/plans` | POST | Generate a new plan |
| `/plans` | GET | List stored plans |
| `/sources` | GET | List ingested knowledge sources |
| `/feedback` | POST | Submit plan feedback |
| `/metrics` | GET | Prometheus metrics export |

**🔧 Middleware:** CORS enabled for all origins.

---

### 🔧 Cache — `cache/redis_cache.py` (68 lines)

**🎯 Purpose:** Async Redis JSON cache with graceful no-op degradation. Used by the **WebCrawler** to cache HTTP responses, avoiding redundant network calls.

**📊 Class: `RedisCache`**

| Method | Purpose |
|--------|---------|
| `get_json(key)` | Retrieve cached dict value. Returns `None` if disabled, Redis unavailable, key missing, or JSON invalid |
| `set_json(key, value, ttl_seconds)` | Store dict as JSON with TTL. Uses `SETEX` for atomic set-with-expiry |
| `close()` | Clean up connection — tries `aclose()` first, falls back to `close()` |

**🔑 Internal Methods:**

| Method | Purpose |
|--------|---------|
| `_namespaced_key(key)` | Prefixes key with `redis_cache_namespace` (default: `agentic-travel-planner`) |
| `_get_client()` | Lazy-init Redis client on first use. Raises `RuntimeError` only if enabled but `redis` package missing |

**📊 Design Patterns:**

- **Lazy connection** — `_client` is `None` until first `get_json()` or `set_json()` call
- **Graceful degradation** — every operation wrapped in `try/except`; failures return `None` silently
- **Disabled-by-default** — `redis_cache_enabled = False` in settings; all methods return immediately if disabled
- **JSON-only** — stores/retrieves only `dict` values; non-dict JSON results are rejected

**🔀 Integration with WebCrawler (`ingestion/crawler.py:51-83`):**

```
WebCrawler.fetch(url, backend)
  ├── cache_key = f"crawl:{backend}:{sha256(url)}"
  ├── cached = RedisCache.get_json(cache_key)  ← check cache first
  │   └── if hit → return CrawlResult(cache_hit=True)
  ├── result = _fetch_{backend}(url)           ← actual HTTP call
  └── RedisCache.set_json(cache_key, result)   ← store for next time
```

**⚙️ Configuration (from `config/settings.py`):**

| Setting | Default | Purpose |
|---------|---------|---------|
| `redis_url` | `redis://localhost:6379/0` | Connection string |
| `redis_cache_enabled` | `False` | Master on/off switch |
| `redis_cache_namespace` | `agentic-travel-planner` | Key prefix to avoid collisions |
| `redis_cache_ttl_seconds` | `3600` (1 hour) | Default expiry |
| `redis_socket_timeout_seconds` | `1.0` | Connection timeout |

**💡 Tip:** To enable, set `REDIS_CACHE_ENABLED=true` in `.env` and ensure Redis is running. The crawler will automatically cache all fetch results — useful when re-ingesting the same URLs across multiple runs.

---

## 🧭 Navigation Guide — Where to Start

### 🚀 "I want to understand how a travel plan gets generated"

```
1️⃣  Start here → domain/models.py
    Read PlanningRequest and PlanningResponse — these are the input/output contracts

2️⃣  Then → api/main.py
    See the POST /plans endpoint that receives requests

3️⃣  Then → services/planner.py
    The thin service that calls the pipeline

4️⃣  Then → pipeline/agentic_pipeline.py
    The main orchestrator — this is the heart of the system

5️⃣  Then → pipeline/graph.py
    The LangGraph state machine — 4 nodes in sequence

6️⃣  Then → pipeline/prompts.py
    How the LLM prompt is constructed

7️⃣  Then → llm/provider.py
    How the LLM is called and JSON is parsed
```

### 🔍 "I want to understand the RAG retrieval system"

```
1️⃣  Start here → domain/models.py
    Read SourceDocument and RetrievedContext

2️⃣  Then → retrieval/vector_store.py
    ChromaDB storage and retrieval

3️⃣  Then → retrieval/chunker.py
    How documents are split into chunks

4️⃣  Then → retrieval/reranker.py
    How results are re-scored

5️⃣  Then → tools/web_search.py
    Live web search integration

6️⃣  Then → tools/place_intel.py
    Venue opening hours lookup

7️⃣  Then → tools/weather.py
    Weather data integration
```

### 📥 "I want to understand knowledge ingestion"

```
1️⃣  Start here → domain/models.py
    Read SourceSeed, SourceManifest, SourceDocument, IngestedSourceRecord

2️⃣  Then → ingestion/service.py
    The main ingestion orchestrator

3️⃣  Then → ingestion/connectors.py
    How different source types are fetched

4️⃣  Then → ingestion/crawler.py
    Web crawling with multiple backends

5️⃣  Then → ingestion/manifest.py
    Manifest file loading

6️⃣  Then → storage/ingestion_store.py
    SQLite persistence of ingestion records

7️⃣  Then → ingestion/cli.py
    CLI commands for ingestion
```

### 🎨 "I want to understand the UI"

```
1️⃣  Start here → app/streamlit_app.py
    The entire UI is in this one file

2️⃣  Then → domain/models.py
    Read PlanningRequest to understand the form fields

3️⃣  Then → api/main.py
    See what the UI calls on the backend

4️⃣  Then → config/settings.py
    See api_base_url and other UI-relevant settings
```

### 📊 "I want to understand observability & monitoring"

```
1️⃣  Start here → observability/metrics.py
    Prometheus counters and histograms

2️⃣  Then → observability/langsmith.py
    LangSmith tracing configuration

3️⃣  Then → api/main.py
    See where metrics are recorded (REQUEST_COUNT, REQUEST_LATENCY)

4️⃣  Then → config/settings.py
    See all observability-related settings
```

### 🧪 "I want to understand evaluation"

```
1️⃣  Start here → domain/models.py
    Read RagEvaluationCase and RagEvaluationReport

2️⃣  Then → evaluation/ragas_pipeline.py
    The full RAGAS evaluation pipeline

3️⃣  Then → evaluation/cli.py
    CLI commands for running evaluations

4️⃣  Then → config/settings.py
    See evaluation_dir and related settings
```

---

## 🔀 Request Flow — End to End

### 📝 Complete Request Lifecycle

```
🖥️  USER interacts with Streamlit UI
    │
    ├── Fills form: destination="Kyoto", interests="temples, food"
    ├── Selects: provider=openai, model=gpt-4o-mini
    ├── Sets: trip_length=4, budget=midrange
    └── Clicks "Generate plan"
    │
    ▼
📡  HTTP POST /plans
    │  Body: PlanningRequest JSON
    │  Headers: Content-Type: application/json
    │
    ▼
🔌  FastAPI receives request (api/main.py:32)
    │  ├── Validates request against PlanningRequest schema
    │  ├── Records Prometheus REQUEST_COUNT metric
    │  ├── Starts REQUEST_LATENCY timer
    │  └── Calls PlannerService.create_plan()
    │
    ▼
🧠  PlannerService (services/planner.py:13)
    │  ├── Creates AgenticTourPlannerPipeline
    │  ├── Calls pipeline.run(request)
    │  └── Saves result via SQLitePlanStore.save_plan()
    │
    ▼
🔄  AgenticTourPlannerPipeline.run() (pipeline/agentic_pipeline.py:44)
    │
    │  ┌──────────────────────────────────────────────────────────┐
    │  │  LangGraph State Machine (pipeline/graph.py)             │
    │  │                                                          │
    │  │  Node 1: gather_context                                  │
    │  │  ├── VectorStore.retrieve() — search knowledge base     │
    │  │  ├── HybridReranker.rerank() — re-score results         │
    │  │  ├── WebSearchTool.suggest_places() — live web search   │
    │  │  ├── PlaceIntelTool.lookup_opening_hours() — venue info │
    │  │  └── WeatherTool.current_weather() — weather data       │
    │  │  → Returns RetrievedContext                              │
    │  │                                                          │
    │  │  Node 2: build_insights                                  │
    │  │  ├── RoutePlannerWorker.build() — route guidance        │
    │  │  ├── BudgetPlannerWorker.build() — budget estimates     │
    │  │  └── TimingPlannerWorker.build() — timing advice        │
    │  │  → Returns PlanningInsights                              │
    │  │                                                          │
    │  │  Node 3: build_prompt                                    │
    │  │  └── build_itinerary_prompt() — assembles full prompt   │
    │  │  → Returns prompt string                                 │
    │  │                                                          │
    │  │  Node 4: generate_plan                                   │
    │  │  └── LLMProvider.complete_json() — call LLM, parse JSON │
    │  │  → Returns plan_json dict                                │
    │  └──────────────────────────────────────────────────────────┘
    │
    ▼
🤖  LLMProvider.complete_json() (llm/provider.py:83)
    │  ├── Resolves provider (openai) and model (gpt-4o-mini)
    │  ├── Builds ChatOpenAI model
    │  ├── Sends: SystemMessage + HumanMessage(prompt)
    │  ├── Parses response as JSON via JsonOutputParser
    │  ├── Retries up to 3 times on failure (tenacity)
    │  └── Falls back to template plan if all providers fail
    │
    ▼
📦  Pipeline assembles PlanningResponse
    │  ├── Parses plan_json into DayPlan objects
    │  ├── Builds Citation list from evidence
    │  ├── Includes PlanningInsights
    │  └── Records provider_used, model_used, generated_at
    │
    ▼
💾  SQLitePlanStore.save_plan()
    │  └── INSERT OR REPLACE INTO plans (...)
    │
    ▼
📡  FastAPI returns PlanningResponse JSON
    │
    ▼
🖥️  Streamlit renders:
    ├── Overview text
    ├── Route/Budget/Timing insights (3 columns)
    ├── Day-by-day itinerary (expandable cards)
    ├── Practical tips
    ├── Citations with links
    └── Feedback form
```

---

## 🛠️ How to Extend & Modify

### ➕ Add a new LLM provider

1. **`config/settings.py`** — Add API key field
2. **`llm/provider.py`** — Add to `_api_key_for()`, `_base_url_for()`, `_build_chat_model()`
3. **`domain/models.py`** — Add to `ProviderName` Literal
4. **`app/streamlit_app.py`** — Add to provider selectbox

### ➕ Add a new tool

1. **`tools/new_tool.py`** — Create tool class
2. **`domain/models.py`** — Add any new response models
3. **`pipeline/agentic_pipeline.py`** — Instantiate tool in `__init__`, call in `gather_context()`
4. **`pipeline/prompts.py`** — Add tool output to evidence blocks

### ➕ Add a new ingestion source type

1. **`domain/models.py`** — Add to `SourceKind` Literal
2. **`ingestion/connectors.py`** — Add `fetch_new_type()` method
3. **`ingestion/service.py`** — Add case in `_fetch_seed()`
4. **`ingestion/cli.py`** — Add CLI command

### ➕ Add a new API endpoint

1. **`api/main.py`** — Add route decorator and handler
2. **`domain/models.py`** — Add request/response models if needed
3. **`app/streamlit_app.py`** — Add UI integration if needed

### ➕ Add a new planning worker

1. **`services/planning_workers.py`** — Create new worker class
2. **`domain/models.py`** — Add output model if needed
3. **`services/planning_workers.py`** — Add to `PlanningInsightsBuilder`
4. **`pipeline/prompts.py`** — Add worker output to prompt

---

## 🚀 Running the Project

### Prerequisites

```bash
# Install with uv (recommended)
cd agentic_travel_planner
uv sync

# Or with pip
pip install -e .
```

### Start the API server

```bash
tour-planner-api
# or
python -m uvicorn agentic_tour_planner.api.main:app --reload --port 8000
```

### Start the Streamlit UI

```bash
tour-planner-ui
# or
streamlit run src/agentic_tour_planner/app/streamlit_app.py --server.port 8501
```

### Ingest knowledge

```bash
# Ingest a Wikivoyage article
tour-planner-ingest wikivoyage "Paris"

# Ingest a web page
tour-planner-ingest web "https://example.com/travel-guide"

# Ingest a YouTube video
tour-planner-ingest youtube "https://youtube.com/watch?v=..."

# Batch ingest from manifest
tour-planner-ingest manifest data/manifest.json --force

# List ingested sources
tour-planner-ingest sources --limit 20
```

### Run evaluations

```bash
# Export RAGAS dataset
tour-planner-eval export data/evaluation_cases.json

# Run RAGAS evaluation
tour-planner-eval ragas data/evaluation_cases.json
```

### Environment Variables

Create a `.env` file in the project root:

```env
# LLM Configuration
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
OPENROUTER_API_KEY=...
XAI_API_KEY=...

# Tools
TAVILY_API_KEY=...
SERPAPI_API_KEY=...
OPENWEATHER_API_KEY=...
GOOGLE_MAPS_API_KEY=...
YOUTUBE_API_KEY=...

# Observability
LANGSMITH_API_KEY=...
LANGSMITH_TRACING=false

# Redis (optional)
REDIS_CACHE_ENABLED=false
REDIS_URL=redis://localhost:6379/0

# App
APP_ENV=development
LOG_LEVEL=INFO
```

---

## 📁 File Index

### Core Application

| File | Lines | Purpose |
|------|-------|---------|
| `domain/models.py` | 206 | All Pydantic data models |
| `config/settings.py` | 83 | Settings & environment loading |
| `pipeline/agentic_pipeline.py` | 73 | Main pipeline orchestrator |
| `pipeline/graph.py` | 50 | LangGraph state machine |
| `pipeline/prompts.py` | 65 | LLM prompt builder |
| `llm/provider.py` | 126 | Multi-provider LLM abstraction |
| `services/planner.py` | 17 | Planner service layer |
| `services/planning_workers.py` | 94 | Deterministic insight workers |
| `api/main.py` | 68 | FastAPI REST endpoints |
| `app/streamlit_app.py` | 228 | Streamlit web UI |

### Retrieval & Tools

| File | Lines | Purpose |
|------|-------|---------|
| `retrieval/vector_store.py` | 116 | ChromaDB vector store |
| `retrieval/chunker.py` | 19 | Text chunking |
| `retrieval/reranker.py` | 32 | Hybrid reranker |
| `tools/web_search.py` | 26 | DuckDuckGo search |
| `tools/place_intel.py` | 54 | Venue opening hours |
| `tools/weather.py` | 30 | Weather data |

### Ingestion

| File | Lines | Purpose |
|------|-------|---------|
| `ingestion/service.py` | 169 | Ingestion orchestrator |
| `ingestion/connectors.py` | 90 | Source fetchers |
| `ingestion/crawler.py` | 170 | Web crawler with backends |
| `ingestion/manifest.py` | 31 | Manifest loader |
| `ingestion/cli.py` | 41 | Ingestion CLI |

### Storage

| File | Lines | Purpose |
|------|-------|---------|
| `storage/sqlite_store.py` | 126 | Plan & feedback storage |
| `storage/ingestion_store.py` | 260 | Ingestion record tracking |

### Observability & Evaluation

| File | Lines | Purpose |
|------|-------|---------|
| `observability/metrics.py` | 19 | Prometheus metrics |
| `observability/langsmith.py` | 16 | LangSmith tracing |
| `evaluation/ragas_pipeline.py` | 101 | RAGAS evaluation |
| `evaluation/cli.py` | 22 | Evaluation CLI |

### Cache

| File | Lines | Purpose |
|------|-------|---------|
| `cache/redis_cache.py` | 68 | Async Redis JSON cache |

### Package Init Files

All `__init__.py` files are minimal package markers.

---

## 🎯 Quick Reference

### Key Entry Points

| Want to... | Start at... |
|------------|-------------|
| Generate a plan | `services/planner.py` → `pipeline/agentic_pipeline.py` |
| Understand data flow | `domain/models.py` |
| Add a feature | `config/settings.py` first |
| Debug LLM calls | `llm/provider.py` |
| Debug retrieval | `retrieval/vector_store.py` |
| Debug ingestion | `ingestion/service.py` |
| Change the UI | `app/streamlit_app.py` |
| Add an API route | `api/main.py` |
| Tune prompts | `pipeline/prompts.py` |
| Add metrics | `observability/metrics.py` |
| Run evaluation | `evaluation/ragas_pipeline.py` |

### Dependency Graph (High Level)

```
domain/models.py ← EVERYTHING imports from here

config/settings.py ← EVERYTHING imports from here

api/main.py → services/planner.py → pipeline/agentic_pipeline.py
                                                    ↓
                                    ┌───────┬───────┼───────┬───────┐
                                    ↓       ↓       ↓       ↓       ↓
                                 llm/   retrieval/  tools/  services/
                               provider.py          planning_workers.py
                                    ↓
                              observability/
                                langsmith.py

ingestion/service.py → ingestion/connectors.py → ingestion/crawler.py
                      → retrieval/vector_store.py
                      → storage/ingestion_store.py

app/streamlit_app.py → api/main.py (via HTTP)
```

---

> 📌 **This guide was generated from a complete reading of all 47 source files in the agentic_travel_planner package. Last updated: May 21, 2026.**
