# Agentic Travel Planner

Production-oriented travel planning system with:

- manifest-driven ingestion for web, Wikivoyage, YouTube, and local files
- crawl backend selection with proxy routing support
- vector retrieval plus hybrid reranking
- specialist planning workers for route, budget, and timing guidance
- FastAPI and Streamlit runtime surfaces
- RAGAS-aligned evaluation pipeline

## Architecture

```text
User
  |
  v
UI / CLI
  - Streamlit UI
  - ingestion CLI
  - evaluation CLI
  |
  v
FastAPI
  - /plans
  - /sources
  - /feedback
  - /metrics
  |
  v
Agentic Planning Layer
  - LangGraph orchestration
  - prompt builder
  - LLM provider adapter
  |
  v
Specialist Workers
  - route worker
  - budget worker
  - timing worker
  |
  v
Context Assembly
  - web search
  - place intel
  - weather
  - retrieval + reranking
  |
  v
Knowledge Base Pipeline
  - IngestionService
  - SourceConnectors
  - WebCrawler
  - proxy routing
  - chunking + embeddings + Chroma
  |
  v
Knowledge Base / Operations Store
  - vector store
  - SQLite plan store
  - ingestion metadata
```

## Key Modules

- `src/agentic_tour_planner/ingestion`
  Ingestion service, manifest loader, crawler, connectors, CLI.
- `src/agentic_tour_planner/retrieval`
  Chunker, vector store, reranker.
- `src/agentic_tour_planner/services/planning_workers.py`
  Deterministic worker agents for routing, budget, and timing.
- `src/agentic_tour_planner/pipeline`
  Prompt builder, LangGraph workflow, orchestration pipeline.
- `src/agentic_tour_planner/evaluation`
  Dataset export and RAGAS scoring flow.
- `src/agentic_tour_planner/api`
  FastAPI app with metrics and persistence.

## Runtime Surfaces

- `tour-planner-api`
- `tour-planner-ui`
- `tour-planner-ingest`
- `tour-planner-eval`
- `streamlit run src/agentic_tour_planner/app/streamlit_app.py`

CLI commands:

```bash
tour-planner-ingest --help
tour-planner-ingest wikivoyage Rome
tour-planner-ingest web https://en.wikivoyage.org/wiki/Rome
tour-planner-ingest youtube https://www.youtube.com/watch?v=dQw4w9WgXcQ
tour-planner-ingest file README.md
tour-planner-ingest manifest examples/rome_manifest.json --limit 2
tour-planner-ingest sources --limit 10

tour-planner-eval --help
tour-planner-eval export examples/ragas_cases.json
tour-planner-eval ragas examples/ragas_cases.json

tour-planner-api
tour-planner-ui
```

API routes:

- `GET /health`
- `POST /plans`
- `GET /plans`
- `GET /sources`
- `POST /feedback`
- `GET /metrics`

## Ingestion

Supported source types:

- `wikivoyage`
- `web`
- `youtube`
- `file`

Manifest example: [examples/rome_manifest.json](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/examples/rome_manifest.json)

Important crawler settings:

- `WEB_CRAWL_BACKEND=trafilatura|httpx|crawl4ai`
- `PROXY_ROUTING_STRATEGY=direct|round_robin|hash`
- `OUTBOUND_PROXY_URLS=["http://proxy-a","http://proxy-b"]`
- `CRAWL_MAX_CONCURRENCY=4`

`crawl4ai` is optional and exposed as an install extra:

```bash
pip install -e '.[crawl]'
```

## Evaluation

The evaluation pipeline can:

- export dataset rows from curated cases
- run a real RAGAS evaluation when runtime dependencies are available
- fall back to lightweight heuristic scoring so CI or local smoke runs do not hard-fail

Example cases: [examples/ragas_cases.json](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/examples/ragas_cases.json)

## Docker

Build and run the API container:

```bash
docker build -t agentic-travel-planner:latest .
docker run --rm -p 8000:8000 --env-file .env agentic-travel-planner:latest
```

Run ingestion inside the image:

```bash
docker run --rm --env-file .env agentic-travel-planner:latest \
  tour-planner-ingest manifest examples/rome_manifest.json --limit 2
```

Files:

- [Dockerfile](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/Dockerfile)
- [.dockerignore](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/.dockerignore)

## Kubernetes

Example manifests:

- [k8s/configmap.yaml](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/k8s/configmap.yaml)
- [k8s/deployment.yaml](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/k8s/deployment.yaml)
- [k8s/service.yaml](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/k8s/service.yaml)

Apply them:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

Create the secret before deployment if you use external providers:

```bash
kubectl create secret generic agentic-travel-planner-secrets \
  --from-literal=OPENAI_API_KEY=your-key
```

The sample deployment mounts `/app/data` as an `emptyDir`. For production, replace that with a persistent volume for Chroma and SQLite.

## Development Notes

- LLM calls degrade to a deterministic JSON fallback when no provider credentials or local model runtime is available.
- Retrieval also works in a fallback in-memory mode when Chroma or embedding runtime is unavailable.
- SQLite stores both ingestion metadata and saved plan history under `data/operations/plans.db`.

## Quick Start

See [QUICKSTART.md](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/QUICKSTART.md).
