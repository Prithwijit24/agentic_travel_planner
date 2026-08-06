# 🗺️ Agentic Travel Planner — Complete Codebase Guide

> **A production-oriented, AI-powered travel planning system** built with FastAPI, a Streamlit UI, a rich-CLI, a direct-httpx multi-provider LLM layer, and deterministic guard rails.

---

## 📋 Table of Contents

- [🏗️ Overall Architecture](#️-overall-architecture)
- [📦 Module-by-Module Deep Dive](#-module-by-module-deep-dive)
- [🧭 Request Flow — End to End](#-request-flow--end-to-end)
- [💾 Configuration](#-configuration)
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
                               │ HTTP POST /plans (+ SSE progress)
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        🔌  FASTAPI API                             │
│                 src/agentic_tour_planner/api/main.py                │
│   Routes: /plans, /plans/{id}/images, /feedback, /metrics, /health  │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  🔄  AGENTIC PIPELINE                               │
│              src/agentic_tour_planner/pipeline/                     │
│      agentic_pipeline.py (planner + detailed stages, dedupe)        │
│      prompts.py  day_clustering.py  travel_constraints.py           │
└───────────────┬───────────────────────────────┬────────────────────┘
                │                               │
                ▼                               ▼
┌───────────────────────────────┐   ┌─────────────────────────────────┐
│  LLM PROVIDER (llm/provider)   │   │  SPECIALIST WORKERS              │
│  priority routing, failover,   │   │  services/planning_workers.py    │
│  cooldowns, per-provider time │   │  route / budget / timing +       │
│                               │   │  heuristic fallback              │
└───────────────────────────────┘   └─────────────────────────────────┘
        ▲                                       ▲
        │ tools/ ai_stack_client (search/news) │
        │ services/news_service (DDGS fallback)│
        │ geonames/ (search + geo clustering)  │
        │ images/ (destination photography)    │
        ▼                                       │
┌─────────────────────────────────────────────────────────────────────┐
│                        🗄️  OPERATIONS STORE                          │
│              src/agentic_tour_planner/storage/sqlite_store.py        │
│                (plan history + feedback, data/operations/plans.db)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Module-by-Module Deep Dive

### 🧠 LLM Layer — `llm/`

#### `llm/provider.py` (28KB) — **the core adapter**

**🎯 Purpose:** Talks to Mark trending LLM providers over plain `httpx`.

- Providers are tried in `PROVIDER_PRIORITY` (`oraclellm`, `agnes`, `nararouter`, `llm7io`, `opencode`).
- Non-OpenAI gateways (e.g. oraclellm) use a `{model, prompt, system_prompt, temperature}` payload; responses come back as `{"response": ...}` — adapted by `_payload_for` / `_content_of`.
- Per-provider timeouts, cooldown marking on failure, and redirect handling.
- `_models_for(provider)` resolves planner/worker models (model-list fallback supported even when unused).

#### `llm/hooks.py`
Metrics bus (`CallMetrics`, `metrics_bus`) subscribed to by the CLI; consumed for wall-clock reporting.

### 🔄 Pipeline — `pipeline/`

- **`agentic_pipeline.py`** — orchestrates the run: base itinerary (planner LLM), deterministic geo day-clustering via `balanced_geo_cluster`, per-day detailed places, day-theme realignment, and a `_dedupe_detailed_days` guard (drops cross-day/same-day repeats, strips markdown).
- **`prompts.py`** — prompt builders for itinerary/planned/detailed stages, plus `strip_place_markdown`.
- **`day_clustering.py`** — balanced geo clustering of POIs into day groups.
- **`travel_constraints.py`** — soft place-count/region constraints for clustering.
- **`output_builder.py`** — normalizes pipeline + detailed + images into one dict for API response.

### 👷 Services — `services/`

- **`planning_workers.py`** — route / budget / timing workers. LLM JSON is validated by pydantic; on schema violations `_safe_build` falls back to `_heuristic` deterministic outputs.
- **`news_service.py`** — AI-stack `/news` with DDGS fallback, LLM summarization, 1h in-memory cache.
- **`cost_estimator.py`** — deterministic per-day cost lines (transport, hotels, meals, flights, tickets).

### 🛠️ Tools — `tools/`

- **`ai_stack_client.py`** — HTTP client for the AI Infra Stack (search/crawl/news/cache endpoints).
- **`weather.py`** — OpenWeather snapshot for the plan.
- **`map_tool.py`** — folium map generation for the UI.
- **`api_client.py` / `http_util.py`** — generic async HTTP helpers backing the above.

### 🖼️ Images — `images/`

- **`pipeline.py`** — resolves images for many places concurrently (cached, UNSPLASH/openverse/etc.).
- **`processor.py`** — download + PIL-based smart-crop/NSFW logic.
- **`sources.py`** — image source adapters (including DDGS + AI-stack).
- **`_stack.py`** — lazy singleton for the AI-stack client; **`cache.py`** storage.

### 🌍 Geography — `geonames/`

- **`index.py`** — in-memory geo search index (marisa + rapidfuzz) for place autocomplete/clustering.
- **`parser.py`** — geonames dump parsing.

### 📦 Domain & Storage

- **`domain/models.py`** — pydantic `PlanningRequest` → `PlanningResponse`, workers, detailed, weather, image, events.
- **`storage/sqlite_store.py`** — plan history + feedback persistence.
- **`config/settings.py`** — merges per-module `.yml` (config/) with env overrides; `get_settings()` cached.

---

## 🧭 Request Flow — End to End

1. **UI/CLI** → `POST /plans` or CLI `plan`/`interactive` returns a `request_id` and starts an async job through `_run_plan_job`.
2. **Pipeline** (`AgenticTourPlannerPipeline.run`) builds a `PlanningRequest`-shaped base:
   - Base itinerary via the **planner LLM** (deepseek-r1-80k on oraclellm by default).
   - Day realignment deterministic clustering of POIs.
3. **Refinements** run in parallel:
   - Detailed places (per-day LLM, minutes) — deduplicated and markdown-cleaned.
   - Image resolution (I/O, minutes).
4. **Output** `output_builder.build_output(...)` merges everything; wall time / LLM-usage ride on the response payload.
5. **Persistence** `SQLitePlanStore.save_plan`; **SSE** heartbeat + steps stream over `/plans/stream/{request_id}`.

---

## 💾 Configuration

- `config/general.yml` — app env/name/log level, bind host, AI-stack credentials.
- `config/llm.yml` — `default_llm_provider`, provider blocks with `planner_model`/`worker_model` and `planner_timeout`/`worker_timeout`.
- `config/api.yml`, `config/storage.yml` — server + SQLite paths.
- `.env` overrides: env var keys are case-insensitive overrides (e.g. `ORACLELLM_API_KEY`, `OPERATIONS_DB_PATH`).

---

## 🛠️ How to Extend & Modify

- **Add a provider** → `llm.yml` (provider block + credentials) and, only if the API shape differs, add adapters in `llm/provider.py` (`_payload_for`, `_content_of`, `_timeout_for`).
- **Change clustering** → `pipeline/day_clustering.py` (target range via `parse_place_range`).
- **Add a worker** → mirror pattern in `services/planning_workers.py` + heuristic fallback.
- **Change plan output contract** → `pipeline/output_builder.py` and the annotated fields in `domain/models.py`.
- **New API route** → `api/main.py` (metrics + SSE in `api/events.py`).

---

## 🚀 Running the Project

```bash
uv pip install -e .
tour-planner-api          # FastAPI on :8000
tour-planner-ui           # Streamlit UI
tour-planner-plan interactive
```

---

## 📁 File Index

- `api/` — FastAPI app + SSE events + image endpoints
- `app/` — Streamlit UI
- `cli/` — rich CLI (`plan.py`)
- `config/` — settings loader + yaml
- `domain/` — pydantic models
- `geonames/` — place search/parse
- `images/` — image pipeline
- `llm/` — provider + hooks
- `pipeline/` — orchestration, prompts, clustering, constraints, output
- `services/` — workers, news, cost
- `storage/` — SQLite
- `tools/` — ai_stack, weather, maps, http helpers
- `utils/` — logging, profiler
- `tests/unit` — pytest unit suite (no live external services)
