# Streamlit Form Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hardcoded model/provider dropdowns with dynamic llm.yml data, increase trip duration slider to 40 days, and add fuzzy autocomplete searchboxes for origin and destination fields.

**Architecture:** Import `LLMProvider` to dynamically populate provider/model selectboxes from llm.yml. Replace `st.text_input` for origin/destination with `st_searchbox` from `streamlit_searchbox` package, wired to `geonames.index.search_places` for fuzzy city autocomplete. Move origin/destination outside the form since `st_searchbox` doesn't work inside `st.form`.

**Tech Stack:** Streamlit, streamlit_searchbox, geonames.index.search_places, LLMProvider.list_providers()/list_models()

## Global Constraints

- Python >=3.11
- Streamlit >=1.40.2
- streamlit_searchbox already installed and importable
- geonames.index.search_places already implemented with fuzzy matching
- LLMProvider.list_providers() and list_models(provider) read from llm.yml at runtime

---

### Task 1: Dynamic Provider/Model Selection from llm.yml

**Files:**
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1391-1398` (PROVIDERS/MODELS_MAP constants)
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1439-1443` (form selectbox widgets)
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1684-1687` (sidebar display)

**Interfaces:**
- Consumes: `LLMProvider.list_providers() -> list[str]`, `LLMProvider.list_models(provider: str) -> list[str]`
- Produces: Dynamic selectbox options that update when provider changes

- [ ] **Step 1: Add LLMProvider import**

At line 976 of streamlit_app.py, after the existing imports, add:

```python
from agentic_tour_planner.llm.provider import LLMProvider
```

- [ ] **Step 2: Replace hardcoded PROVIDERS and MODELS_MAP**

Replace lines 1391-1398 (the `PROVIDERS = [...]` and `MODELS_MAP = {...}` block) with a helper that builds the maps dynamically:

```python
def _build_provider_models() -> tuple[list[str], dict[str, list[str]]]:
    """Pull providers and their models from llm.yml via LLMProvider."""
    try:
        llm = LLMProvider()
        providers = llm.list_providers()
        models_map: dict[str, list[str]] = {}
        for p in providers:
            models_map[p] = llm.list_models(p)
        return providers, models_map
    except Exception:
        return ["agnes"], {"agnes": ["agnes-2.0-flash"]}


PROVIDERS, MODELS_MAP = _build_provider_models()
```

- [ ] **Step 3: Update form selectbox for provider**

The form selectbox at line 1439 already uses `PROVIDERS` — it will now get the dynamic list. No change needed to the widget itself, but ensure the `index` fallback handles missing values:

Replace the provider selectbox block (lines 1439-1443):

```python
with conf_c1:
    provider = st.selectbox(
        "🤖 Model Provider",
        PROVIDERS,
        index=PROVIDERS.index(st.session_state.provider) if st.session_state.provider in PROVIDERS else 0,
    )
with conf_c2:
    current_models = MODELS_MAP.get(provider, ["default"])
    model_index = current_models.index(st.session_state.model) if st.session_state.model in current_models else 0
    model = st.selectbox("⚙️ Model Name", current_models, index=model_index)
```

- [ ] **Step 4: Update sidebar provider display**

Replace lines 1684-1687 in the sidebar section:

```python
p_idx = PROVIDERS.index(st.session_state.provider) if st.session_state.provider in PROVIDERS else 0
st.selectbox("🤖 Model Provider", PROVIDERS, disabled=True, index=p_idx, key="sidebar_provider_disabled")
current_models = MODELS_MAP.get(st.session_state.provider, ["default"])
m_idx = current_models.index(st.session_state.model) if st.session_state.model in current_models else 0
st.selectbox("⚙️ Model Name", current_models, disabled=True, index=m_idx, key="sidebar_model_disabled")
```

- [ ] **Step 5: Verify syntax compiles**

Run: `python -m py_compile src/agentic_tour_planner/app/streamlit_app.py`

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/app/streamlit_app.py
git commit -m "feat(ui): dynamic provider/model selection from llm.yml"
```

---

### Task 2: Increase Days Slider Max to 40

**Files:**
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1426`

**Interfaces:** None (standalone change)

- [ ] **Step 1: Change slider range**

Replace line 1426:

```python
# Before:
with c3: days = st.slider("📅 Duration (Days)", 1, 7, 4)

# After:
with c3: days = st.slider("📅 Duration (Days)", 1, 40, 4)
```

- [ ] **Step 2: Verify syntax compiles**

Run: `python -m py_compile src/agentic_tour_planner/app/streamlit_app.py`

- [ ] **Step 3: Commit**

```bash
git add src/agentic_tour_planner/app/streamlit_app.py
git commit -m "feat(ui): increase trip duration slider to 40 days"
```

---

### Task 3: Add Fuzzy Autocomplete Searchboxes for Origin and Destination

**Files:**
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:970-976` (imports)
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1002-1006` (helper functions section)
- Modify: `src/agentic_tour_planner/app/streamlit_app.py:1419-1423` (form fields)

**Interfaces:**
- Consumes: `streamlit_searchbox.st_searchbox`, `agentic_tour_planner.geonames.index.search_places`
- Produces: `_search_suggestions(query: str) -> list[str]` function, searchbox widgets outside the form

- [ ] **Step 1: Add imports**

At line 976 of streamlit_app.py, after the existing imports, add:

```python
from streamlit_searchbox import st_searchbox
from agentic_tour_planner.geonames.index import search_places
```

- [ ] **Step 2: Add search suggestions helper**

In the helper functions section (after `clean_html` around line 1006), add:

```python
def _search_suggestions(query: str) -> list[str]:
    if len(query) < 1:
        return []
    try:
        results = search_places(query, limit=8)
        return [r.name for r in results]
    except Exception:
        return []
```

- [ ] **Step 3: Move origin/destination outside the form and replace with searchbox**

The form currently starts at line 1419 with `with st.form("trip_planner_form"):`. Origin and destination are at lines 1422-1423 inside the form.

Move origin and destination **before** the form, and replace `st.text_input` with `st_searchbox`:

Before the `with st.form(...)` block (after the column layout), add:

```python
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    destination = st_searchbox(
        _search_suggestions,
        placeholder="e.g. Sikkim, Kyoto, Paris... (click to select)",
        label="🌍 Destination *",
        default="",
        default_use_searchterm=True,
        clear_on_submit=False,
        edit_after_submit="option",
        debounce=200,
        key="dest_searchbox",
    )
    origin = st_searchbox(
        _search_suggestions,
        placeholder="e.g. Kolkata, Mumbai... (click to select)",
        label="📍 Origin",
        default="",
        default_use_searchterm=True,
        clear_on_submit=False,
        edit_after_submit="option",
        debounce=200,
        key="origin_searchbox",
    )

    with st.form("trip_planner_form"):
        st.markdown("### Trip Details")
        c3, c4 = st.columns(2)
        with c3: days = st.slider("📅 Duration (Days)", 1, 40, 4)
        with c4: month = st.selectbox("🌤️ Travel Month", ["September", "October", "November"], index=0)
        # ... rest of form fields (budget, travelers, transport, interests, config) unchanged
```

Remove the old `origin = st.text_input(...)` and `destination = st.text_input(...)` lines from inside the form.

- [ ] **Step 4: Clean up form_data to handle searchbox values**

In the submit handler (line 1448-1464), ensure destination and origin are cleaned (take first part before comma):

```python
if submit:
    st.session_state.provider = provider
    st.session_state.model = model
    st.session_state.form_data = {
        "destination": destination.split(",")[0].strip() if destination else "",
        "origin": origin.split(",")[0].strip() if origin else None,
        "days": int(days),
        "month": month,
        "budget": budget,
        "travelers": int(travelers),
        "transport": transport,
        "interests": interests,
    }
    st.session_state.form_submitted = True
    st.session_state.is_loading = True
    main_area.empty()
    st.rerun()
```

- [ ] **Step 5: Verify syntax compiles**

Run: `python -m py_compile src/agentic_tour_planner/app/streamlit_app.py`

- [ ] **Step 6: Run existing tests to ensure no regressions**

Run: `.venv/bin/python -m pytest tests/unit/test_events.py tests/unit/test_api_streaming.py tests/unit/test_images.py tests/unit/test_models.py tests/integration/test_api.py -v`

- [ ] **Step 7: Commit**

```bash
git add src/agentic_tour_planner/app/streamlit_app.py
git commit -m "feat(ui): add fuzzy autocomplete searchboxes for origin/destination"
```
