# ✨ Agentic Travel Planner: Your Intelligent Trip Companion! ✨

Welcome to the **Agentic Travel Planner**! 🌍 This project brings you a production-oriented travel planning system designed to make your adventures seamless and smart.

---

## 🌟 Key Features & Capabilities:

-   **📚 Manifest-driven Ingestion:** Easily load data from diverse sources like the web, Wikivoyage, YouTube, and local files.
-   **⚙️ Flexible Crawl Backend:** Choose your crawling backend with robust proxy routing support.
-   **🔍 Advanced Retrieval:** Benefit from vector retrieval coupled with hybrid reranking for highly relevant information.
-   **👷 Specialist Planning Workers:** Get expert guidance for crafting your route, managing your budget, and optimizing your trip timing.
-   **⚡ Robust Runtime Surfaces:** Powered by **FastAPI** for the backend and a stunning **Streamlit UI** for an interactive experience.
-   **📊 RAGAS-aligned Evaluation:** An integrated pipeline to rigorously assess and improve planning performance.

---

## 🏗️ Architecture Overview:

Dive into the intelligent design powering your travel plans!

```text
User
  |
  v
UI / CLI (Your Interaction Hub!)
  - Streamlit UI
  - ingestion CLI
  - evaluation CLI
  |
  v
FastAPI (The Brains of the Operation!)
  - /plans
  - /sources
  - /feedback
  - /metrics
  |
  v
Agentic Planning Layer (Orchestrating Intelligence!)
  - LangGraph orchestration
  - prompt builder
  - LLM provider adapter
  |
  v
Specialist Workers (Your Personal Travel Experts!)
  - route worker
  - budget worker
  - timing worker
  |
  v
Context Assembly (Gathering All the Info!)
  - web search
  - place intel
  - weather
  - retrieval + reranking
  |
  v
Knowledge Base Pipeline (Building Your Data Foundation!)
  - IngestionService
  - SourceConnectors
  - WebCrawler
  - proxy routing
  - chunking + embeddings + Chroma
  |
  v
Knowledge Base / Operations Store (Where Knowledge Resides!)
  - vector store
  - SQLite plan store
  - ingestion metadata
```

---

## 📂 Key Modules: Where the Magic Happens!

Explore the core components that make this planner tick:

-   **`src/agentic_tour_planner/ingestion`**: 📥 Handles all aspects of data ingestion, including the service, manifest loader, crawler, connectors, and CLI.
-   **`src/agentic_tour_planner/retrieval`**: 🧠 Manages information retrieval with chunking, vector storage, and reranking.
-   **`src/agentic_tour_planner/services/planning_workers.py`**: 🤖 Contains the deterministic worker agents specialized in routing, budgeting, and timing.
-   **`src/agentic_tour_planner/pipeline`**: 🚀 Orchestrates the planning workflow using a prompt builder, LangGraph, and the main pipeline.
-   **`src/agentic_tour_planner/evaluation`**: 📈 Provides tools for dataset export and RAGAS scoring to measure performance.
-   **`src/agentic_tour_planner/api`**: 🔗 Defines the FastAPI application, complete with metrics and persistence capabilities.

---

## 🚀 Runtime Surfaces: Get Started!

Interact with the Agentic Travel Planner using these powerful entry points:

-   `tour-planner-api`
-   `tour-planner-ui`
-   `tour-planner-ingest`
-   `tour-planner-eval`
-   `streamlit run src/agentic_tour_planner/app/streamlit_app.py`

### 💻 CLI Commands (Examples):

```bash
# Ingestion
tour-planner-ingest --help
tour-planner-ingest wikivoyage Rome
tour-planner-ingest web https://en.wikivoyage.org/wiki/Rome
tour-planner-ingest youtube https://www.youtube.com/watch?v=dQw4w9WgXcQ
tour-planner-ingest file README.md
tour-planner-ingest manifest examples/rome_manifest.json --limit 2
tour-planner-ingest sources --limit 10

# Evaluation
tour-planner-eval --help
tour-planner-eval export examples/ragas_cases.json
tour-planner-eval ragas examples/ragas_cases.json

# Running the applications
tour-planner-api
tour-planner-ui
```

### 🌐 API Routes:

-   `GET /health`
-   `POST /plans`
-   `GET /plans`
-   `GET /sources`
-   `POST /feedback`
-   `GET /metrics`

---

## 📥 Ingestion: Fueling Your Knowledge Base

The planner supports various source types to build its comprehensive knowledge base:

-   `wikivoyage` 🗺️
-   `web` 🕸️
-   `youtube` 🎬
-   `file` 📄

**Manifest Example:** Check out the [Rome manifest example](examples/rome_manifest.json) for structured ingestion.

### ⚙️ Important Crawler Settings:

-   `WEB_CRAWL_BACKEND=trafilatura|httpx|crawl4ai` (Choose your web crawling engine!)
-   `PROXY_ROUTING_STRATEGY=direct|round_robin|hash` (Control your proxy usage!)
-   `OUTBOUND_PROXY_URLS=["http://proxy-a","http://proxy-b"]` (List your proxy servers!)
-   `CRAWL_MAX_CONCURRENCY=4` (Optimize for speed!)

_Note:_ `crawl4ai` is an optional extra: `pip install -e '.[crawl]'`

---

## 📊 Evaluation: Measuring Success!

The integrated evaluation pipeline helps you understand and improve the planner's performance:

-   **Export Dataset Rows:** Easily generate datasets from curated cases.
-   **RAGAS Evaluation:** Run comprehensive RAGAS evaluations when dependencies are met.
-   **Lightweight Heuristic Scoring:** Enjoy fallback scoring for CI/CD or local smoke tests, ensuring stability.

**Example Cases:** See [examples/ragas_cases.json](examples/ragas_cases.json) for evaluation examples.

---

## 🐳 Docker: Containerized Convenience!

Build and run your Agentic Travel Planner with Docker:

```bash
# Build the Docker image
docker build -t agentic-travel-planner:latest .

# Run the API container with environment variables from .env
docker run --rm -p 8000:8000 --env-file .env agentic-travel-planner:latest
```

### Run Ingestion within the Docker Image:

```bash
docker run --rm --env-file .env agentic-travel-planner:latest \
  tour-planner-ingest manifest examples/rome_manifest.json --limit 2
```

**Relevant Files:**

-   [Dockerfile](Dockerfile)
-   [.dockerignore](.dockerignore)

---

## ☸️ Kubernetes: Orchestrate Your Deployment!

Deploy your Agentic Travel Planner seamlessly on Kubernetes:

**Example Manifests:**

-   [k8s/configmap.yaml](k8s/configmap.yaml)
-   [k8s/api-deployment.yaml](k8s/api-deployment.yaml)
-   [k8s/api-service.yaml](k8s/api-service.yaml)
-   [k8s/ui-deployment.yaml](k8s/ui-deployment.yaml)
-   [k8s/ui-service.yaml](k8s/ui-service.yaml)

### Apply them to your cluster:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/ui-deployment.yaml
kubectl apply -f k8s/ui-service.yaml
```

**⚠️ Important:** If you're using external providers, create your secrets _before_ deployment:

```bash
kubectl create secret generic agentic-travel-planner-secrets \
  --from-literal=OPENAI_API_KEY=your-key
```

_Note:_ The sample deployment uses `/app/data` as an `emptyDir`. For production environments, consider replacing this with a **persistent volume** for Chroma and SQLite to ensure data durability.

---

## 💡 Development Notes & Fallbacks:

-   **LLM Fallback:** When no provider credentials or local model runtime are available, LLM calls gracefully degrade to a **deterministic JSON fallback**.
-   **Retrieval Fallback:** Retrieval also works in a fallback **in-memory mode** if Chroma or the embedding runtime is inaccessible.
-   **Data Storage:** SQLite stores both ingestion metadata and your saved plan history within `data/operations/plans.db`.

---

## 🚀 Quick Start:

Ready to jump in? Check out the detailed setup and usage instructions in our [**QUICKSTART.md**](QUICKSTART.md) guide!