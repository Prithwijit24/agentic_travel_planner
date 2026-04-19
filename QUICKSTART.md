# Quickstart

## 1. Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

Optional browser-assisted crawling:

```bash
pip install -e '.[crawl]'
```

## 2. Configure

Create `.env` in the repo root:

```env
APP_ENV=development
LOG_LEVEL=INFO

DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o-mini
OLLAMA_BASE_URL=http://localhost:11434

WEB_CRAWL_BACKEND=trafilatura
PROXY_ROUTING_STRATEGY=direct
VECTOR_STORE_DIR=./data/chroma
KNOWLEDGE_BASE_DIR=./data/knowledge
OPERATIONS_DB_PATH=./data/operations/plans.db
EVALUATION_DIR=./data/evaluation

OPENAI_API_KEY=
GOOGLE_API_KEY=
OPENWEATHER_API_KEY=
GOOGLE_MAPS_API_KEY=
```

Without provider keys or a running local model, the planner still works through a deterministic fallback response path.

## 3. Ingest Data

Manifest-driven ingestion:

```bash
tour-planner-ingest manifest examples/rome_manifest.json --limit 2
```

One-off ingestion:

```bash
tour-planner-ingest wikivoyage Rome
tour-planner-ingest web https://www.lonelyplanet.com/italy/rome
tour-planner-ingest file README.md
```

List indexed sources:

```bash
tour-planner-ingest sources --limit 10
```

## 4. Run The API

```bash
tour-planner-api
```

Example request:

```bash
curl -X POST http://127.0.0.1:8000/plans \
  -H 'Content-Type: application/json' \
  -d '{
    "destination": "Rome",
    "origin": "Milan",
    "trip_length_days": 4,
    "interests": ["history", "food", "walkable neighborhoods"],
    "budget_level": "midrange",
    "travel_month": "September",
    "include_live_data": false
  }'
```

## 5. Run The UI

```bash
streamlit run src/agentic_tour_planner/app/streamlit_app.py
```

## 6. Run Evaluation

Export dataset rows:

```bash
tour-planner-eval export examples/ragas_cases.json
```

Run RAGAS scoring:

```bash
tour-planner-eval ragas examples/ragas_cases.json
```

## 7. Useful Files

- [pyproject.toml](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/pyproject.toml)
- [examples/rome_manifest.json](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/examples/rome_manifest.json)
- [examples/ragas_cases.json](/home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner/examples/ragas_cases.json)
