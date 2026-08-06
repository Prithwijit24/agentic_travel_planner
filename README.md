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
