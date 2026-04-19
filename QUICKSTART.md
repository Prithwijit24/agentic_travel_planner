# ✨ Quickstart to Agentic Tour Planner! ✨

🚀 Get ready to plan your next adventure with ease! This guide will get you up and running in no time.

---

## 1. 🛠️ Install

First things first, set up your Python environment and install the necessary packages.

```bash
python -m venv .venv            # Create a virtual environment
source .venv/bin/activate       # Activate the environment (Linux/macOS)
# .venv\Scripts\activate       # Activate the environment (Windows)
pip install --upgrade pip       # Ensure pip is up-to-date
pip install -e .                # Install the tour planner in editable mode
```

_Optional:_ If you want to enable browser-assisted crawling for richer data ingestion:

```bash
pip install -e '.[crawl]'       # Install with web crawling dependencies
```

---

## 2. ⚙️ Configure Your Environment

Create a `.env` file in the root of this project to customize settings and add your API keys.

```env
APP_ENV=development
LOG_LEVEL=INFO

# 🤖 LLM Provider Settings
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=gpt-4o-mini
OLLAMA_BASE_URL=http://localhost:11434 # For local LLMs like Ollama

# 🕸️ Web Crawling & Data Storage
WEB_CRAWL_BACKEND=trafilatura
PROXY_ROUTING_STRATEGY=direct
VECTOR_STORE_DIR=./data/chroma
KNOWLEDGE_BASE_DIR=./data/knowledge
OPERATIONS_DB_PATH=./data/operations/plans.db
EVALUATION_DIR=./data/evaluation

# 🔑 Your API Keys (Crucial for full functionality!)
OPENAI_API_KEY=
GOOGLE_API_KEY=
OPENWEATHER_API_KEY=
GOOGLE_MAPS_API_KEY=
```

💡 **Note:** The planner can still operate with a deterministic fallback if API keys or a local model aren't configured, but its capabilities will be limited.

---

## 3. 📚 Ingest Data

Populate your knowledge base with travel information.

### Manifest-driven ingestion (recommended for structured data):

```bash
tour-planner-ingest manifest examples/rome_manifest.json --limit 2 # Ingest data for Rome from a manifest file
```

### One-off ingestion (for quick additions):

```bash
tour-planner-ingest wikivoyage Rome                 # Add data from Wikivoyage about Rome
tour-planner-ingest web https://www.lonelyplanet.com/italy/rome # Crawl a specific URL
tour-planner-ingest file README.md                  # Ingest content from a local file
```

### List your indexed sources:

```bash
tour-planner-ingest sources --limit 10              # See what data you've ingested
```

---

## 4. 🚀 Run The API

Start the backend API server to handle planning requests.

```bash
tour-planner-api                                    # Launch the FastAPI server
```

### Example API Request (using `curl`):

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

---

## 5. 🖥️ Run The UI

Fire up the interactive Streamlit user interface.

```bash
streamlit run src/agentic_tour_planner/app/streamlit_app.py # Start the web UI
```

---

## 6. 📊 Run Evaluation

Assess the performance and quality of your planner.

### Export dataset rows for evaluation:

```bash
tour-planner-eval export examples/ragas_cases.json  # Prepare evaluation data
```

### Run RAGAS scoring to get detailed metrics:

```bash
tour-planner-eval ragas examples/ragas_cases.json   # Analyze planner responses with RAGAS
```

---

## 7. 📁 Useful Files

Quick links to important project files:

-   [**`pyproject.toml`**](pyproject.toml) - Project configuration and dependencies.
-   [**`examples/rome_manifest.json`**](examples/rome_manifest.json) - Example data ingestion manifest for Rome.
-   [**`examples/ragas_cases.json`**](examples/ragas_cases.json) - Example evaluation dataset for RAGAS.