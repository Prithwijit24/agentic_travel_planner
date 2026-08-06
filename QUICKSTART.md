# ✨ Quickstart to Agentic Tour Planner! ✨

🚀 Get ready to plan your next adventure with ease! This guide will get you up and running in no time.

---

## 1. 🛠️ Install

First things first, set up your Python environment and install the necessary packages.

```bash
uv venv                       # Create a virtual environment
source .venv/bin/activate     # Activate the environment (Linux/macOS)
uv pip install -e .           # Install the tour planner in editable mode
```

---

## 2. ⚙️ Configure Your Environment

Create a `.env` file in the root of this project to customize settings and add your API keys.

```env
APP_ENV=development
LOG_LEVEL=INFO

# 🤖 LLM Provider Settings
DEFAULT_LLM_PROVIDER=oraclellm
ORACLELLM_API_KEY=            # Required for the oraclellm provider

# 🔑 Your API Keys (Crucial for full functionality!)
OPENWEATHER_API_KEY=
GOOGLE_MAPS_API_KEY=
UNSPLASH_ACCESS_KEY=          # For destination imagery
PEXELS_API_KEY=
```

💡 **Note:** The planner fails over across providers in priority order (`oraclellm`, `agnes`, `nararouter`, `llm7io`, `opencode`) and can degrade to deterministic fallbacks if no provider is reachable, but its capabilities will be limited.

---

## 3. 🚀 Run The API

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

## 4. 🖥️ Run The UI

Fire up the interactive Streamlit user interface.

```bash
tour-planner-ui                                     # Start the web UI
# or: streamlit run src/agentic_tour_planner/app/streamlit_app.py
```

---

## 5. ⌨️ Run The CLI

Plan a trip directly from the terminal.

```bash
tour-planner-plan interactive                       # Guided interactive mode
tour-planner-plan plan "Rome" --days 4 --origin "Milan"   # One-shot plan
tour-planner-plan news --destination Rome           # Live destination news
```

---

## 6. 📁 Useful Files

Quick links to important project files:

-   [**`pyproject.toml`**](pyproject.toml) - Project configuration and dependencies.
-   [**`src/agentic_tour_planner/config/llm.yml`**](src/agentic_tour_planner/config/llm.yml) - LLM provider and model configuration.
