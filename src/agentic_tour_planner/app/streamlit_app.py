import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import streamlit as st
from streamlit_searchbox import st_searchbox

from agentic_tour_planner.domain.models import BudgetLevel, PlanningRequest
from agentic_tour_planner.geonames.index import search_places
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.services.news_service import NewsService

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


@st.cache_resource
def _get_ui_jobs() -> dict[str, dict]:
    return {}


_UI_JOBS = _get_ui_jobs()

# --- PAGE CONFIGURATION ---
st.set_page_config(
    page_title="Agentic Tour Planner · Sikkim", page_icon="🗺️", layout="wide", initial_sidebar_state="expanded"
)

# --- STATE MANAGEMENT ---
if "form_submitted" not in st.session_state:
    st.session_state.form_submitted = False
if "is_loading" not in st.session_state:
    st.session_state.is_loading = False
if "plan" not in st.session_state:
    st.session_state.plan = None
if "images" not in st.session_state:
    st.session_state.images = []
if "provider" not in st.session_state:
    st.session_state.provider = "agnes"
if "planner_model" not in st.session_state:
    st.session_state.planner_model = "agnes-2.0-flash"
if "worker_model" not in st.session_state:
    st.session_state.worker_model = "agnes-2.0-flash"


# --- HELPER FUNCTIONS ---
def clean_html(html_str: str) -> str:
    lines = html_str.split("\n")
    cleaned_lines = [line.lstrip() for line in lines]
    return "\n".join(cleaned_lines).strip()


def html_escape(text: str) -> str:
    """Minimal HTML escape for user/LLM text injected via unsafe_allow_html."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# Markdown category -> colour used for keyword highlighting (mirrors the CLI).
_KEYWORD_COLORS = {
    "place": "#0078D4",
    "altitude": "#ff8c00",
    "person": "#c026d3",
    "deity": "#ffb900",
    "other": "#00b294",
}


def render_highlighted(text: str, keywords: list | None = None) -> str:
    """Render a markdown-ish string as HTML with applying bold, italics and coloured keywords.

    keywords: a list of {"text": ..., "category": ...} dicts. Words found verbatim
    in the text are wrapped in a bold category colour. ``**bold**`` / ``*italic*``
    markdown is converted to ``<b>`` / ``<i>``. Safe for ``unsafe_allow_html``.
    """
    s = html_escape(text or "")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?!\*)\*(?!\*)", r"<i>\1</i>", s)
    for kw in keywords or []:
        if isinstance(kw, dict):
            term, cat = kw.get("text"), kw.get("category", "other")
        else:
            term = getattr(kw, "text", None)
            cat = getattr(kw, "category", "other")
        if not term:
            continue
        color = _KEYWORD_COLORS.get(cat, _KEYWORD_COLORS["other"])
        pattern = re.compile(r"(?i)\b(" + re.escape(str(term)) + r")\b")
        s = pattern.sub(rf'<b style="color: {color};">\1</b>', s)
    return s


_LOADING_ANIMATION_DIR = Path(__file__).resolve().parent.parent / "loading_animations"


@st.cache_data(show_spinner=False)
def _load_loading_svg(filename: str) -> str:
    with (_LOADING_ANIMATION_DIR / filename).open(encoding="utf-8") as fh:
        return str(fh.read())


def _render_loading_animation(svg_filename: str, title: str, subtitle: str) -> str:
    """Return HTML for a nice animated SVG loader (World_map / Notifications)."""
    svg = _load_loading_svg(svg_filename)
    return clean_html(
        f"""
<div style="display:flex; flex-direction:column; align-items:center; justify-content:center;
            gap:14px; padding:36px 24px; background:#f8f9fb; border:1px solid #e6e7eb;
            border-radius:16px; text-align:center; margin-bottom:20px;">
    <div style="width:220px; height:220px; display:flex; align-items:center; justify-content:center;">
        {svg}
    </div>
    <div style="font-size:17px; font-weight:600; color:#1d1d1f;">{title}</div>
    <div style="font-size:14px; color:#6e6e73;">{subtitle}</div>
</div>
"""
    )


def _search_suggestions(query: str) -> list[str]:
    if len(query) < 1:
        return []
    try:
        results = search_places(query, limit=8)
        return [r.name for r in results]
    except Exception:
        return []


def fluent_card(title, color, content_html):
    color_map = {"blue": "bg-blue", "cyan": "bg-cyan", "teal": "bg-teal", "gold": "bg-gold", "purple": "bg-purple"}
    bar_cls = color_map.get(color, "bg-blue")
    html = f"""
<div class="card">
<div class="accent-bar {bar_cls}"></div>
<div class="card-title">{title}</div>
{content_html}
</div>
"""
    return clean_html(html)


# --- API CLIENT HELPERS ---
def _build_request_from_form(
    destination: str,
    origin: str | None,
    days: int,
    interests: list[str],
    budget: str,
    month: str,
    notes: str | None,
    provider: str | None,
    planner_model: str | None,
    worker_model: str | None,
    places_per_day: str,
    transport: str,
    travelers: int,
    live: bool = False,
) -> PlanningRequest:
    """Convert form fields to a PlanningRequest."""
    transport_map = {
        "Public Transport": "public",
        "Private Cab": "car",
        "Rental Car": "car",
    }
    return PlanningRequest(
        destination=destination,
        origin=origin or None,
        trip_length_days=days,
        interests=interests,
        budget_level=cast(BudgetLevel, budget.lower()),
        travel_month=month,
        notes=notes or None,
        provider=provider or None,
        planner_model=planner_model or None,
        worker_model=worker_model or None,
        include_live_data=live,
        places_per_day=places_per_day,
        transport_mode=transport_map.get(transport, "public"),
        travelers=travelers,
    )


async def _call_plans_api(request: PlanningRequest) -> dict:
    """POST to /plans and return the response."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        r = await client.post(f"{API_BASE_URL}/plans", json=request.model_dump(mode="json"))
        r.raise_for_status()
        return cast(dict, r.json())


async def _stream_logs(request_id: str, callback) -> None:
    """Connect to SSE stream and call callback for each event."""
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client,
        client.stream("GET", f"{API_BASE_URL}/plans/stream/{request_id}") as response,
    ):
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                event_data = json.loads(line[6:])
                callback(event_data)
                # The done event is terminal: stop reading so the job thread is
                # never left blocked on a server that keeps the stream open.
                if event_data.get("event") == "done":
                    break


async def _fetch_images(plan_id: str) -> dict:
    """GET /plans/{plan_id}/images."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API_BASE_URL}/plans/{plan_id}/images")
        r.raise_for_status()
        return cast(dict, r.json())


def _start_generation_job(
    form_data: dict,
    provider: str | None,
    planner_model: str | None,
    worker_model: str | None,
) -> str:
    job_id = str(uuid4())
    _UI_JOBS[job_id] = {
        "status": "running",
        "progress": 0.05,
        "message": "Sending request to API server...",
        "plan": None,
        "images": {},
        "error": None,
        "started_at": time.time(),
        "logs": [],
    }

    def run_job() -> None:
        job = _UI_JOBS[job_id]
        job["logs"] = [
            {"time": "00:00", "text": "🚀 Initializing Agentic Tour Planner...", "class": "info"},
            {
                "time": "00:00",
                "text": f"🤖 Connecting to {planner_model} via {provider}...",
                "class": "info",
            },
            {"time": "00:00", "text": "📡 Sending request to API server...", "class": "info"},
        ]
        job["started_at"] = time.time()
        request_obj = _build_request_from_form(
            destination=form_data.get("destination", ""),
            origin=form_data.get("origin"),
            days=form_data.get("days", 3),
            interests=form_data.get("interests", []),
            budget=form_data.get("budget", "Midrange"),
            month=form_data.get("month", ""),
            notes=None,
            provider=provider,
            planner_model=planner_model,
            worker_model=worker_model,
            places_per_day="3-5",
            transport=form_data.get("transport", "Public Transport"),
            travelers=form_data.get("travelers", 1),
        )

        try:
            response_data = asyncio.run(_call_plans_api(request_obj))
            if response_data.get("status") == "error":
                raise RuntimeError(response_data.get("error") or "Unknown error")

            stream_result: dict[str, Any] = {"plan": response_data.get("plan"), "images": [], "error": None}
            step_counter = [0]
            total_steps = 4

            def on_event(event_data):
                event_type = event_data.get("event", "")
                message = event_data.get("message", "")
                elapsed = time.time() - job["started_at"]
                ts = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
                if event_type in ("step", "debug", "metric", "info", "log", "progress"):
                    job["logs"].append({"time": ts, "text": message, "class": "info"})
                if event_type == "step":
                    step_counter[0] += 1
                    job["progress"] = min(step_counter[0] / total_steps, 0.95)
                    job["message"] = message
                elif event_type == "error":
                    job["logs"].append({"time": ts, "text": f"❌ {message}", "class": "error"})
                    stream_result["error"] = message
                    job["message"] = f"Error: {message}"
                elif event_type == "done":
                    detail = event_data.get("detail") or {}
                    if detail.get("status") == "error":
                        job["logs"].append(
                            {"time": ts, "text": f"❌ {detail.get('error') or message}", "class": "error"}
                        )
                        stream_result["error"] = detail.get("error") or message
                    else:
                        job["logs"].append({"time": ts, "text": f"✅ {message}", "class": "success"})
                    if detail.get("response"):
                        plan_payload = {**detail["response"]}
                        if detail.get("detailed"):
                            plan_payload["detailed"] = detail["detailed"]
                        stream_result["plan"] = plan_payload
                    if isinstance(detail.get("images"), list):
                        stream_result["images"] = detail["images"]
                    job["progress"] = 1.0
                    job["message"] = "Complete!"

            asyncio.run(_stream_logs(response_data["request_id"], on_event))

            if stream_result["error"] or not stream_result["plan"]:
                raise RuntimeError(stream_result["error"] or "No plan returned by API")

            plan_data = stream_result["plan"]
            if stream_result["images"]:
                job["images"] = {"images": stream_result["images"]}
            else:
                try:
                    job["images"] = asyncio.run(_fetch_images(plan_data["plan_id"]))
                except Exception:
                    job["images"] = {}

            job["plan"] = plan_data
            job["status"] = "done"
        except Exception as e:
            job["error"] = str(e)
            job["status"] = "error"

    threading.Thread(target=run_job, daemon=True).start()
    return job_id


def _plan_to_display_dict(plan_data: dict, request: dict) -> dict:
    """Convert API PlanningResponse JSON + original request into the flat dict format the UI expects."""
    itinerary = plan_data.get("itinerary", [])

    # Build lookup from detailed plan (richer descriptions, ~200 words)
    detailed_lookup = {}
    detailed_data = plan_data.get("detailed")
    if detailed_data and isinstance(detailed_data, dict):
        for dday in detailed_data.get("days", []):
            day_num = dday.get("day")
            places_by_name = {}
            for place in dday.get("places", []):
                pname = place.get("name", "")
                if pname:
                    places_by_name[pname] = place
            detailed_lookup[day_num] = places_by_name

    def _is_real_place(name: str) -> bool:
        n = (name or "").strip()
        n_lower = n.lower()
        if not n or len(n) < 3:
            return False
        junk = {
            "morning",
            "late morning",
            "midday",
            "afternoon",
            "late afternoon",
            "evening",
            "early",
            "late",
            "noon",
            "dawn",
            "dusk",
            "night",
            "breakfast",
            "lunch",
            "dinner",
            "brunch",
            "arrival",
            "arrive",
            "departure",
            "depart",
            "transit",
            "check-in",
            "check-out",
            "drive",
            "transfer",
            "return",
            "free time",
            "en route",
            "explore",
            "visit",
            "walk",
            "rest",
            "optional place",
        }
        if n_lower in junk or any(seg.strip().lower() in junk for seg in n.split(",")):
            return False
        return not ("optional place" in n_lower or re.search(r"\d", n))

    def _text(*values) -> str:
        # LLM JSON may carry nulls for known keys (defaults in .get() only apply
        # to MISSING keys), so coerce the first non-empty value to a safe string.
        for v in values:
            if v:
                return str(v)
        return ""

    display_itinerary = []

    for day in itinerary:
        day_num = day.get("day")
        day_detailed = detailed_lookup.get(day_num, {})
        spots = []
        for spot in day.get("spots", []):
            spot_name = spot.get("name", "")
            if not _is_real_place(spot_name):
                continue
            det = day_detailed.get(spot_name, {})

            desc = _text(det.get("description"), spot.get("description"))
            key_note = _text(det.get("key_note"), spot.get("history"), spot.get("description"))[:120]
            opening_hours = (
                _text(
                    det.get("opening_closing"),
                    f"{spot.get('opening_hours', '')} \u2013 {spot.get('closing_hours', '')}".strip(" \u2013"),
                )
                or "Not available"
            )
            transport_text = _text(det.get("transport"), spot.get("transport")) or "Local transport"
            spots.append(
                {
                    "name": spot_name,
                    "description": desc,
                    "hours": opening_hours,
                    "best_time": _text(det.get("best_time"), spot.get("best_time")),
                    "transport": transport_text,
                    "key_note": key_note,
                    "keywords": det.get("keywords") or [],
                    "is_optional": det.get("is_optional") or spot.get("is_optional") or False,
                    "lat": spot.get("lat", 0),
                    "lon": spot.get("lon", 0),
                    "image_query": spot.get("image_query", spot.get("name", "")),
                }
            )

        w = day.get("weather") or {}
        display_day = {
            "day": day.get("day", 0),
            "theme": day.get("theme", ""),
            "plan": day.get("summary", ""),
            "hotel": day.get("hotel_recommendation", ""),
            "weather": {
                "day_temp": f"{w.get('temperature_c', 'N/A')}°C" if w.get("temperature_c") is not None else "N/A",
                "night_temp": f"{w.get('temperature_night_c', 'N/A')}°C"
                if w.get("temperature_night_c") is not None
                else "N/A",
                "sunrise": w.get("sunrise", "N/A"),
                "sunset": w.get("sunset", "N/A"),
                "humidity": f"{w.get('humidity_percent', 'N/A')}%" if w.get("humidity_percent") is not None else "N/A",
                "rain": f"{w.get('rainfall_chance_percent', 'N/A')}%"
                if w.get("rainfall_chance_percent") is not None
                else "N/A",
            },
            "spots": spots,
            "morning": day.get("morning", []),
            "afternoon": day.get("afternoon", []),
            "evening": day.get("evening", []),
            "meals": day.get("meals", []),
            "logistics": day.get("logistics", []),
            "transport": day.get("transport", ""),
        }
        display_itinerary.append(display_day)

    cost = plan_data.get("cost_estimate") or {}
    overall = cost.get("overall") or {}
    daily = cost.get("daily", [])

    display_cost = {
        "daily": [
            {
                "day": d.get("day", 0),
                "breakdown": " | ".join(
                    f"{item.get('label', '')}: {item.get('amount', 0)}" for item in d.get("items", [])
                ),
                "subtotal": f"{d.get('subtotal', 0)} INR" if d.get("subtotal") else "N/A",
            }
            for d in daily
        ],
        "overall": {
            "per_person_total": overall.get("per_person_total"),
            "members": overall.get("members", 1),
            "grand_total": overall.get("grand_total"),
        },
    }

    citations = []
    for c in plan_data.get("citations", []):
        citations.append(
            {
                "title": c.get("title", ""),
                "url": c.get("url", "#"),
            }
        )

    return {
        "destination": request.get("destination", ""),
        "origin": request.get("origin", ""),
        "duration": request.get("days", 0),
        "month": request.get("month", ""),
        "budget": request.get("budget", ""),
        "travelers": request.get("travelers", 1),
        "overview": plan_data.get("overview", ""),
        "wall_time_s": plan_data.get("wall_time_s"),
        "llm_usage": plan_data.get("llm_usage") or {},
        "booking_resources": {
            "flights": ["makemytrip", "agoda", "goibibo"],
            "hotels": ["makemytrip", "agoda", "goibibo", "booking"],
            "accessories": ["Amazon", "flipkart"],
        },
        "monthly_weather": plan_data.get("monthly_weather", ""),
        "itinerary": display_itinerary,
        "practical_tips": plan_data.get("practical_tips", []),
        "cost_estimate": display_cost,
        "sources": citations,
    }


# --- CUSTOM CSS (APPLE UI + MICROSOFT FLUENT COLORS) ---
def load_css():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'SF Pro Display', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #1d1d1f;
}

.main .block-container {
    padding-top: 3rem;
    padding-bottom: 5rem;
    max-width: 1200px;
}

#MainMenu, footer { visibility: hidden; }

h1, h2, h3, h4 {
    font-weight: 600 !important;
    letter-spacing: -0.02em;
    color: #1d1d1f !important;
}

:root {
    --ms-blue: #0078D4;
    --ms-cyan: #00BCF2;
    --ms-teal: #00B294;
    --ms-gold: #FFB900;
    --ms-purple: #5C2D91;
    --ms-red: #E81123;
    --apple-gray-bg: #f5f5f7;
    --apple-border: #d2d2d7;
}

.card {
    background: #ffffff;
    border: 1px solid var(--apple-border);
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 16px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
    height: 100%;
    box-sizing: border-box;
}
.card:hover { box-shadow: 0 8px 24px rgba(0,0,0,0.06); }
.card-title {
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 12px;
    color: #6e6e73;
}

.accent-bar {
    height: 4px;
    border-radius: 2px;
    margin-bottom: 16px;
}
.bg-blue { background-color: var(--ms-blue); }
.bg-cyan { background-color: var(--ms-cyan); }
.bg-teal { background-color: var(--ms-teal); }
.bg-gold { background-color: var(--ms-gold); }
.bg-purple { background-color: var(--ms-purple); }

section[data-testid="stSidebar"] {
    background-color: #f5f5f7;
    border-right: 1px solid var(--apple-border);
}
section[data-testid="stSidebar"] [role="radiogroup"] label {
    background-color: transparent;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 4px;
    transition: background-color 0.2s;
}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background-color: #e8e8ed;
}
section[data-testid="stSidebar"] [data-checked="true"] {
    background-color: var(--ms-blue) !important;
    color: white !important;
}
section[data-testid="stSidebar"] [data-checked="true"] span {
    color: white !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: var(--apple-gray-bg);
    padding: 6px;
    border-radius: 12px;
    border: 1px solid var(--apple-border);
}
.stTabs [data-baseweb="tab"] {
    padding: 10px 24px;
    border-radius: 8px;
    font-weight: 500;
    color: #6e6e73;
}
.stTabs [aria-selected="true"] {
    background-color: #ffffff;
    color: #1d1d1f !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

/* General Sidebar/Button Styling */
.stButton > button {
    background-color: var(--ms-blue);
    color: white;
    border-radius: 980px;
    padding: 12px 24px;
    font-weight: 600;
    border: none;
    width: 100%;
    transition: transform 0.1s, background-color 0.2s;
}
.stButton > button:hover {
    background-color: #0064b0;
    color: white;
}
.stButton > button:active {
    transform: scale(0.98);
}

.weather-strip {
    display: flex;
    justify-content: space-between;
    background: #fbfbfd;
    border: 1px solid var(--apple-border);
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 24px;
    font-size: 14px;
    color: #3a3a3c;
    flex-wrap: wrap;
    gap: 10px;
}
.weather-item b { color: #1d1d1f; }

.w-day { font-weight: 700; color: #FF8C00; }
.w-night { font-weight: 700; color: #0078D4; }
.w-sunrise { font-weight: 700; color: #FF4500; }
.w-sunset { font-weight: 700; color: #6e6e73; }
.w-humidity { font-weight: 700; color: #00BCF2; }
.w-rain { font-weight: 700; color: #D300C9; }

div[data-baseweb="select"] > div {
    background-color: #f5f5f7 !important;
    border-color: #d2d2d7 !important;
}
div[data-baseweb="select"] > div > div {
    color: #6e6e73 !important;
}

.spot-wrapper {
    display: flex;
    gap: 16px;
    margin-bottom: 16px;
    align-items: stretch;
}

.spot-text-card {
    flex: 3;
    background: #ffffff;
    border: 1px solid var(--apple-border);
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.03);
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
}

.spot-image-card {
    flex: 2;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--apple-border);
    box-shadow: 0 4px 12px rgba(0,0,0,0.03);
    box-sizing: border-box;
    background-color: #f5f5f7;
    min-height: 250px;
}

.spot-image-card img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}
</style>
""",
        unsafe_allow_html=True,
    )


load_css()


def _build_provider_models() -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    """Pull providers and their planner/worker models from llm.yml via LLMProvider."""
    try:
        llm = LLMProvider()
        providers = llm.list_providers()
        planner_map: dict[str, list[str]] = {}
        worker_map: dict[str, list[str]] = {}
        for p in providers:
            cfg = llm.providers.get(p, {})
            planner_val = cfg.get("planner_model")
            worker_val = cfg.get("worker_model")
            planner_map[p] = [planner_val] if isinstance(planner_val, str) else (planner_val or [])
            worker_map[p] = [worker_val] if isinstance(worker_val, str) else (worker_val or [])
        return providers, planner_map, worker_map
    except Exception:
        return ["agnes"], {"agnes": ["agnes-2.0-flash"]}, {"agnes": ["agnes-2.0-flash"]}


PROVIDERS, PLANNER_MODELS, WORKER_MODELS = _build_provider_models()

# --- INPUT PAGE ---
if not st.session_state.form_submitted and not st.session_state.is_loading:
    # Hide sidebar on input page for a cleaner look
    st.markdown(
        '<style>[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}</style>',
        unsafe_allow_html=True,
    )
    st.markdown("<style>.main .block-container {max-width: 800px;}</style>", unsafe_allow_html=True)

    # Show the reason a previous generation attempt failed instead of hiding it.
    plan_error = st.session_state.pop("plan_error", None)
    if plan_error:
        st.error(f"⚠️ Plan generation failed: {plan_error}")
        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    st.markdown(
        clean_html("""
<h1 style="font-size: 48px; text-align: center; margin-bottom: 0;">Agentic Tour Planner 🗺️</h1>
<p style="font-size: 20px; color: #6e6e73; text-align: center; margin-bottom: 40px;">Design your perfect trip with AI-powered insights</p>
"""),
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        destination = st_searchbox(
            _search_suggestions,
            placeholder="e.g. Sikkim, Kyoto, Paris... (type to search)",
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
            placeholder="e.g. Kolkata, Mumbai... (type to search)",
            label="📍 Origin",
            default="",
            default_use_searchterm=True,
            clear_on_submit=False,
            edit_after_submit="option",
            debounce=200,
            key="origin_searchbox",
        )

        st.markdown("### Configuration")
        conf_c1, conf_c2, conf_c3 = st.columns(3)
        with conf_c1:
            provider = st.selectbox(
                "🤖 Model Provider",
                PROVIDERS,
                index=PROVIDERS.index(st.session_state.provider) if st.session_state.provider in PROVIDERS else 0,
            )
        with conf_c2:
            current_planner = PLANNER_MODELS.get(provider, ["default"]) or ["default"]
            planner_index = (
                current_planner.index(st.session_state.planner_model)
                if st.session_state.planner_model in current_planner
                else 0
            )
            planner_model = st.selectbox("🧠 Planner Model", current_planner, index=planner_index)
        with conf_c3:
            current_worker = WORKER_MODELS.get(provider, ["default"]) or ["default"]
            worker_index = (
                current_worker.index(st.session_state.worker_model)
                if st.session_state.worker_model in current_worker
                else 0
            )
            worker_model = st.selectbox("🛠️ Worker Model", current_worker, index=worker_index)

        with st.form("trip_planner_form"):
            st.markdown("### Trip Details")
            c3, c4 = st.columns(2)
            with c3:
                days = st.slider("📅 Duration (Days)", 1, 40, 4)
            with c4:
                month = st.selectbox(
                    "🌤️ Travel Month",
                    [
                        "January",
                        "February",
                        "March",
                        "April",
                        "May",
                        "June",
                        "July",
                        "August",
                        "September",
                        "October",
                        "November",
                        "December",
                    ],
                    index=8,
                )

            c5, c6 = st.columns(2)
            with c5:
                budget = st.selectbox("💰 Budget", ["Budget", "Midrange", "Luxury"], index=1)
            with c6:
                travelers = st.number_input("👥 Travelers", 1, 10, 4)

            transport = st.selectbox("🚇 Transport Mode", ["Public Transport", "Private Cab", "Rental Car"], index=0)
            # Dynamic interests from API (per-destination)
            default_interests = ["Nature", "Monasteries", "Adventure", "Culture"]
            if destination and len(destination) >= 2:
                try:
                    import requests as _req
                    resp = _req.get(f"http://127.0.0.1:8000/destinations/{destination.split(',')[0].strip()}/interests", timeout=5)
                    if resp.status_code == 200:
                        default_interests = resp.json().get("tags", default_interests)
                except Exception:
                    pass  # Fall back to static list if API is unreachable

            interests = st.multiselect(
                "🎯 Interests", default_interests, default_interests[:2] if default_interests else []
            )
            st.caption("Interests are based on what's available at your destination. Leave unselected for a balanced mix.")

            st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

            submit = st.form_submit_button("Generate Itinerary ✨", use_container_width=True)

            if submit:
                dest_clean = destination.split(",")[0].strip() if destination else ""
                if not dest_clean or len(dest_clean) < 2:
                    st.error("Please enter a valid destination (at least 2 characters)")
                else:
                    st.session_state.provider = provider
                    st.session_state.planner_model = planner_model
                    st.session_state.worker_model = worker_model
                    st.session_state.form_data = {
                        "destination": dest_clean,
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
                    st.session_state.loading_seconds = 0
                    st.rerun()

# --- LOADING PAGE ---
elif st.session_state.is_loading:
    # Hide sidebar on loading page
    st.markdown(
        '<style>[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display: none !important;}</style>',
        unsafe_allow_html=True,
    )
    st.markdown("<style>.main .block-container {max-width: 820px; padding-top: 4rem;}</style>", unsafe_allow_html=True)

    # Static header (spinner + title) — rendered once, stable
    st.iframe(
        """<!DOCTYPE html>
<html><head><style>
@keyframes pulse-ring {
  0%   { transform: scale(0.2); opacity: 0.9; }
  60%  { opacity: 0.3; }
  100% { transform: scale(1.9); opacity: 0; }
}
.ring {
  transform-box: fill-box;
  transform-origin: center;
  animation: pulse-ring 2.4s cubic-bezier(0.25, 0.1, 0.25, 1) infinite;
}
.ring:nth-of-type(2) { animation-delay: 0.6s; }
.ring:nth-of-type(3) { animation-delay: 1.2s; }
.ring:nth-of-type(4) { animation-delay: 1.8s; }
</style></head><body style="margin:0;display:flex;align-items:center;justify-content:center;height:100vh;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="100%" height="100%">
  <g fill="none" stroke="#269eff" stroke-width="4">
    <g class="ring"><circle cx="60" cy="60" r="26"/></g>
    <g class="ring"><circle cx="60" cy="60" r="26"/></g>
    <g class="ring"><circle cx="60" cy="60" r="26"/></g>
    <g class="ring"><circle cx="60" cy="60" r="26"/></g>
  </g>
</svg>
</body></html>""",
        height=140,
    )

    st.markdown(
        """
        <style>
        .tour-loader-box { text-align: center; margin-bottom: 24px; }
        .tour-loader-box h3 { margin: 0; color: #1d1d1f; font-size: 20px; font-weight: 600; }
        .tour-loader-box p { color: #6e6e73; margin-top: 8px; font-size: 14px; }
        .tour-terminal { background: #ffffff; border: 1px solid #d2d2d7; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.03); overflow: hidden; text-align: left; margin-bottom: 16px; }
        .tour-terminal-head { background: #f5f5f7; padding: 12px 16px; border-bottom: 1px solid #d2d2d7; display: flex; align-items: center; gap: 8px; justify-content: space-between; }
        .tour-terminal-dot { width: 12px; height: 12px; border-radius: 50%; }
        .tour-dot-red { background: #ff5f56; }
        .tour-dot-yellow { background: #ffbd2e; }
        .tour-dot-green { background: #27c93f; }
        .tour-terminal-body { padding: 20px 24px; font-family: 'SF Mono', 'Courier New', monospace; font-size: 14px; color: #3a3a3c; background: #fbfbfd; min-height: 280px; max-height: 420px; overflow-y: auto; }
        .tour-log { margin-bottom: 10px; line-height: 1.4; }
        .tour-log-time { color: #8e8e93; margin-right: 8px; }
        .tour-log-success { color: #00B294; }
        .tour-log-info { color: #0078D4; }
        .tour-log-warn { color: #FFB900; }
        .tour-log-error { color: #D0021B; }
        .tour-terminal-clock { font-family: 'SF Mono', 'Courier New', monospace; font-size: 13px; color: #8e8e93; margin-left: auto; }
        </style>
        <div class="tour-loader-box">
            <h3>Crafting your perfect trip...</h3>
            <p>Our AI agents are analyzing routes, weather, and local insights. This may take 10-15 minutes.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    @st.fragment(run_every=1.0)
    def _loading_status() -> None:
        st.session_state.loading_seconds = st.session_state.get("loading_seconds", 0) + 1
        form_data = st.session_state.get("form_data", {})
        if "generation_job_id" not in st.session_state:
            st.session_state.generation_job_id = _start_generation_job(
                form_data,
                st.session_state.provider,
                st.session_state.planner_model,
                st.session_state.worker_model,
            )

        job = _UI_JOBS.get(st.session_state.generation_job_id)
        if job is None:
            st.session_state.plan_error = "Plan generation failed: job state was lost"
            st.session_state.is_loading = False
            st.session_state.form_submitted = False
            st.session_state.pop("generation_job_id", None)
            st.rerun()

        term_lines = "".join(
            f'<div class="tour-log tour-log-{line["class"]}">'
            f'<span class="tour-log-time">[{line["time"]}]</span>{line["text"]}</div>'
            for line in job.get("logs", [])
        )
        st.markdown(
            f"""
            <div class="tour-terminal">
                <div class="tour-terminal-head">
                    <div class="tour-terminal-dot tour-dot-red"></div>
                    <div class="tour-terminal-dot tour-dot-yellow"></div>
                    <div class="tour-terminal-dot tour-dot-green"></div>
                    <span class="tour-terminal-clock">{st.session_state.loading_seconds // 3600:02d}:{st.session_state.loading_seconds % 3600 // 60:02d}:{st.session_state.loading_seconds % 60:02d}</span>
                </div>
                <div class="tour-terminal-body">{term_lines}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        progress_value = job.get("progress", 0.05)
        pct = min(int(progress_value * 100), 100)
        pcol, lcol = st.columns([5, 1], vertical_alignment="center")
        with pcol:
            st.progress(progress_value, text=job.get("message", "Generating itinerary..."))
        with lcol:
            st.markdown(
                f"<div style='text-align:right; font-size:15px; font-weight:600; color:#1d1d1f;'>{pct}%</div>",
                unsafe_allow_html=True,
            )

        if job["status"] == "error":
            # Persist the failure so it is shown on the form page instead of the
            # UI silently dropping the user back without any explanation.
            st.session_state.plan_error = job.get("error") or "Unknown error"
            st.session_state.is_loading = False
            st.session_state.form_submitted = False
            finished_job_id = st.session_state.pop("generation_job_id", None)
            if finished_job_id:
                _UI_JOBS.pop(finished_job_id, None)
            st.rerun()

        if job["status"] == "done":
            plan_data = job["plan"]
            images_data = job.get("images") or {}

            request_dict = {
                "destination": form_data.get("destination", ""),
                "origin": form_data.get("origin", ""),
                "days": form_data.get("days", 3),
                "month": form_data.get("month", ""),
                "budget": form_data.get("budget", "Midrange"),
                "travelers": form_data.get("travelers", 1),
            }

            st.session_state.plan = _plan_to_display_dict(plan_data, request_dict)
            st.session_state.images = images_data.get("images", [])
            # Clear any stale failure banner from a previous attempt.
            st.session_state.pop("plan_error", None)
            st.session_state.is_loading = False
            finished_job_id = st.session_state.pop("generation_job_id", None)
            if finished_job_id:
                _UI_JOBS.pop(finished_job_id, None)
            st.rerun()

    _loading_status()

# --- RESULTS PAGE ---
elif st.session_state.plan is not None:
    plan = st.session_state.plan

    with st.sidebar:
        st.markdown("### 🗺️ Tour Planner")
        st.markdown(f"**Destination:** {plan['destination']}")
        st.markdown(f"**Duration:** {plan['duration']} Days · {plan['month']}")
        st.markdown(f"**Budget:** {plan['budget']} · {plan['travelers']} Travelers")
        st.markdown("<hr style='border: 0; border-top: 1px solid #d2d2d7; margin: 16px 0;'>", unsafe_allow_html=True)

        menu_options = [
            "📄 Overview",
            "🗓️ Daily Itinerary",
            "🗺️ Maps",
            "📰 News",
            "🚇 Resources",
            "💡 Budget & Tips",
        ]
        menu_choice = st.radio("Navigation", menu_options, label_visibility="collapsed")

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
        st.markdown("#### Configuration")

        p_idx = PROVIDERS.index(st.session_state.provider) if st.session_state.provider in PROVIDERS else 0
        st.selectbox("🤖 Model Provider", PROVIDERS, disabled=True, index=p_idx, key="sidebar_provider_disabled")

        current_planner = PLANNER_MODELS.get(st.session_state.provider, ["default"])
        pl_idx = (
            current_planner.index(st.session_state.planner_model)
            if st.session_state.planner_model in current_planner
            else 0
        )
        st.selectbox("🧠 Planner Model", current_planner, disabled=True, index=pl_idx, key="sidebar_planner_disabled")

        current_worker = WORKER_MODELS.get(st.session_state.provider, ["default"])
        w_idx = (
            current_worker.index(st.session_state.worker_model)
            if st.session_state.worker_model in current_worker
            else 0
        )
        st.selectbox("🛠️ Worker Model", current_worker, disabled=True, index=w_idx, key="sidebar_worker_disabled")

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
        if st.button("← Start New Trip"):
            st.session_state.form_submitted = False
            st.session_state.is_loading = False
            st.session_state.plan = None
            st.session_state.images = []
            st.rerun()

    st.markdown(
        clean_html(f"""
<h1 style="font-size: 40px; margin-bottom: 0;">{plan["destination"]} 🏔️</h1>
<p style="font-size: 18px; color: #6e6e73; margin-top: 0;">{plan["duration"]}-Day Itinerary · {plan["month"]} · Origin: {plan["origin"]}</p>
"""),
        unsafe_allow_html=True,
    )

    if menu_choice == "📄 Overview":
        st.markdown("### Trip Overview")

        wall_time = plan.get("wall_time_s")
        if isinstance(wall_time, int | float):
            total_secs = int(wall_time)
            st.success(
                f"⏱️ **Complete wall time: {total_secs // 60} min {total_secs % 60} sec** to produce this response."
            )

        st.markdown(
            clean_html(f"""
<p style="font-size: 16px; line-height: 1.6; color: #3a3a3c;">{render_highlighted(plan["overview"])}</p>
"""),
            unsafe_allow_html=True,
        )

        res_html = f"""
<div style="font-size: 15px; line-height: 1.8; color: #3a3a3c;">
<div style="margin-bottom: 8px;">✈️ <b>Train/Flight:</b> {", ".join(plan["booking_resources"]["flights"])}</div>
<div style="margin-bottom: 8px;">🏨 <b>Hotel booking:</b> {", ".join(plan["booking_resources"]["hotels"])}</div>
<div>🛍️ <b>Accessories:</b> {", ".join(plan["booking_resources"]["accessories"])}</div>
</div>
"""
        st.markdown(fluent_card("Booking & Resources", "purple", clean_html(res_html)), unsafe_allow_html=True)

        weather_html = f"<p style='font-size:14px; color:#3a3a3c;'>{render_highlighted(plan['monthly_weather'])}</p>"
        st.markdown(fluent_card(f"Estimated Weather ({plan['month']})", "cyan", weather_html), unsafe_allow_html=True)

        st.markdown("---")

        llm_usage = plan.get("llm_usage") or {}
        llm_stages_used = list(llm_usage.get("used") or [])
        llm_stages_fallback = list(llm_usage.get("fallback") or [])
        total_stages = len(llm_stages_used) + len(llm_stages_fallback)
        st.success(
            f"🤖 **LLM used in {len(llm_stages_used)} of {max(total_stages, 1)} pipeline stages**"
            + (f" ({', '.join(llm_stages_used)})." if llm_stages_used else ".")
        )
        if llm_stages_fallback:
            st.success(
                f"⚙️ **{len(llm_stages_fallback)} stage(s) fell back to the deterministic approach:** "
                f"{', '.join(llm_stages_fallback)}."
            )
        else:
            st.success("✅ **No LLM stage fell back** — every step used the LLM.")

        st.markdown("---")

    if menu_choice == "🗓️ Daily Itinerary":
        day_tabs = st.tabs([f"Day {d['day']}" for d in plan["itinerary"]])

        for i, day in enumerate(plan["itinerary"]):
            with day_tabs[i]:
                st.markdown(f"#### Day {day['day']} — {day['theme']}")
                st.markdown(
                    clean_html(f"""
<p style="font-size: 15px; color: #3a3a3c; margin-bottom: 24px;">{render_highlighted(day["plan"])}</p>
"""),
                    unsafe_allow_html=True,
                )

                w = day["weather"]
                w_html = f"""
<div class="weather-strip">
<span class="weather-item">🌡️ <b>Day Temp:</b> <span class="w-day">{w["day_temp"]}</span></span>
<span class="weather-item">🌙 <b>Night Temp:</b> <span class="w-night">{w["night_temp"]}</span></span>
<span class="weather-item">🌅 <b>Sunrise:</b> <span class="w-sunrise">{w["sunrise"]}</span></span>
<span class="weather-item">🌇 <b>Sunset:</b> <span class="w-sunset">{w["sunset"]}</span></span>
<span class="weather-item">💧 <b>Humidity:</b> <span class="w-humidity">{w["humidity"]}</span></span>
<span class="weather-item">🌧️ <b>Rain:</b> <span class="w-rain">{w["rain"]}</span></span>
</div>
"""
                st.markdown(clean_html(w_html), unsafe_allow_html=True)

                st.markdown("##### 📍 Spots to Visit")
                for spot in day["spots"]:
                    images = st.session_state.get("images", [])
                    spot_image = next(
                        (
                            img
                            for img in images
                            if (img.get("place_name") or "").strip().lower() == (spot["name"] or "").strip().lower()
                        ),
                        None,
                    )
                    if spot_image and spot_image.get("image_url"):
                        img_url = spot_image["image_url"]
                    else:
                        img_query = spot["name"].replace(" ", ",")
                        img_url = f"https://source.unsplash.com/600x400/?{img_query}"
                    spot_html = f"""
<div class="spot-wrapper">
<div class="spot-text-card">
<div class="accent-bar bg-blue" style="width: 60px; margin-bottom: 16px;"></div>
<div style="font-weight: 600; font-size: 18px; margin-bottom: 8px; color: #1d1d1f;">{html_escape(spot["name"])}{' <span style="color:var(--ms-gold);font-size:14px;">(optional)</span>' if spot.get("is_optional") else ""}</div>
<div style="font-size: 15px; color: #3a3a3c; margin-bottom: 12px; line-height: 1.5;">{render_highlighted(spot["description"], spot.get("keywords"))}</div>
<div style="font-size: 14px; margin-bottom: 6px; color: #3a3a3c;"><b style="color: #1d1d1f;">🕒 Hours:</b> {html_escape(spot["hours"])}</div>
<div style="font-size: 14px; margin-bottom: 6px; color: #3a3a3c;"><b style="color: #1d1d1f;">⏳ Best Time:</b> {render_highlighted(spot["best_time"])}</div>
<div style="font-size: 14px; margin-bottom: 6px; color: #3a3a3c;"><b style="color: #1d1d1f;">🚕 Transport:</b> {render_highlighted(spot["transport"])}</div>
<div style="font-size: 14px; background: #f5f5f7; padding: 12px; border-radius: 8px; margin-top: 12px; color: #3a3a3c; border-left: 4px solid var(--ms-gold);"><b style="color: #1d1d1f;">🔑 Note:</b> {render_highlighted(spot["key_note"])}</div>
</div>
<div class="spot-image-card">
<img src="{img_url}" alt="{html_escape(spot["name"])}">
</div>
</div>
"""
                    st.markdown(clean_html(spot_html), unsafe_allow_html=True)

                hotel_html = f"<p style='font-size:17px; color:#3a3a3c;'>🏨 {render_highlighted(day['hotel'])}</p>"
                st.markdown(fluent_card("Accommodation", "cyan", clean_html(hotel_html)), unsafe_allow_html=True)

    elif menu_choice == "💡 Budget & Tips":
        st.markdown("### 💰 Cost Estimate")
        cost_estimate = plan.get("cost_estimate") or {}
        overall = cost_estimate.get("overall") or {}
        bc1, bc2, bc3 = st.columns(3)
        per_person = overall.get("per_person_total")
        grand_total = overall.get("grand_total")
        per_person_html = f"₹{float(per_person):,.0f}" if isinstance(per_person, int | float) else "N/A"
        grand_total_html = f"₹{float(grand_total):,.0f}" if isinstance(grand_total, int | float) else "N/A"
        with bc1:
            st.markdown(
                fluent_card(
                    "Per Person",
                    "teal",
                    f"<div style='font-size: 24px; font-weight: 700;'>{per_person_html}</div>",
                ),
                unsafe_allow_html=True,
            )
        with bc2:
            st.markdown(
                fluent_card(
                    "Grand Total",
                    "blue",
                    f"<div style='font-size: 24px; font-weight: 700;'>{grand_total_html}</div>",
                ),
                unsafe_allow_html=True,
            )
        with bc3:
            st.markdown(
                fluent_card(
                    "Travelers",
                    "purple",
                    f"<div style='font-size: 24px; font-weight: 700;'>{overall.get('members', 1)}</div>",
                ),
                unsafe_allow_html=True,
            )

        st.markdown("#### Daily Breakdown")
        for daily in cost_estimate.get("daily") or []:
            d_html = f"""
<div style="display: flex; justify-content: space-between; align-items: center;">
<span style="font-size: 14px; color: #3a3a3c;">{daily.get("breakdown", "")}</span>
<span style="font-size: 16px; font-weight: 700; color: var(--ms-teal); white-space: nowrap; margin-left: 16px;">{daily.get("subtotal", "")}</span>
</div>
"""
            st.markdown(
                fluent_card(f"Day {daily.get('day', '')} Costs", "gold", clean_html(d_html)), unsafe_allow_html=True
            )

        st.markdown("### 💡 Practical Tips")
        tips_html = "<ul style='padding-left: 20px; margin: 0;'>"
        for tip in plan.get("practical_tips") or []:
            tips_html += (
                f"<li style='font-size: 14px; color: #3a3a3c; margin-bottom: 10px;'>{render_highlighted(tip)}</li>"
            )
        tips_html += "</ul>"
        st.markdown(
            fluent_card(f"Tips for {plan.get('destination', '')}", "purple", clean_html(tips_html)),
            unsafe_allow_html=True,
        )

    elif menu_choice == "🚇 Resources":
        st.markdown("### 📚 Sources & Citations")
        cit_html = "<div style='display: flex; flex-direction: column; gap: 12px;'>"
        for cit in plan.get("sources") or []:
            cit_html += f"<a href='{cit.get('url', '#')}' target='_blank' style='text-decoration: none; color: var(--ms-blue); background: #f5f5f7; padding: 12px; border-radius: 8px; font-size: 14px; font-weight: 500;'>🔗 {cit.get('title', '')}</a>"
        cit_html += "</div>"
        st.markdown(fluent_card("Citations", "teal", clean_html(cit_html)), unsafe_allow_html=True)

    elif menu_choice == "🗺️ Maps":
        st.markdown("### 📍 Trip Route Map")

        try:
            from streamlit.components.v1 import html as st_html

            from agentic_tour_planner.tools.map_tool import MapTool
        except ImportError as imp_err:
            st.error(f"Map dependencies not available: {imp_err}")
        else:
            loading_placeholder = st.empty()
            loading_placeholder.markdown(
                _render_loading_animation(
                    "World_map.svg",
                    "Plotting your route...",
                    "Geocoding your itinerary places and building the interactive map.",
                ),
                unsafe_allow_html=True,
            )
            try:
                map_tool = MapTool()
                folium_map = map_tool.render_itinerary_map(
                    itinerary=plan.get("itinerary", []),
                    origin=plan.get("origin"),
                    destination=plan.get("destination", ""),
                )
                map_html = folium_map.get_root().render()
                loading_placeholder.empty()
                st_html(map_html, height=620, scrolling=False)

                unresolved = [n for n in getattr(map_tool, "unresolved_locations", []) if n]
                if unresolved:
                    names = "".join(f"<div style='padding:4px 0;'>• {n}</div>" for n in unresolved)
                    st.error(
                        clean_html(
                            f"""
                            <div style='font-weight:600; margin-bottom:6px;'>
                                ⚠️ Could not locate the following places on the map:
                            </div>
                            {names}
                            """
                        ),
                        icon="🚩",
                    )

                st.markdown("<div style='margin-bottom: 16px;'></div>", unsafe_allow_html=True)
                st.info(
                    "ⓘ Markers are color-coded by day. "
                    "Use the layer control (top-right) to toggle days on/off. "
                    "Click a marker for details."
                )
            except Exception as map_err:
                loading_placeholder.empty()
                st.warning(f"Map rendering failed: {map_err}")
                st.info("Map visualization requires the itinerary to have geocodable place names.")

    elif menu_choice == "📰 News":
        st.markdown("### 📰 Recent News")
        dest_name = plan["destination"]
        st.markdown(
            f"<p style='font-size: 15px; color: #6e6e73; margin-bottom: 24px;'>"
            f"Latest news and updates about {dest_name}</p>",
            unsafe_allow_html=True,
        )

        # Check for cached news in session state
        # Include interests in cache key for per-interest deduplication
        _interests = st.session_state.get("form_data", {}).get("interests", [])
        news_key = f"news_{dest_name}:{hash(tuple(_interests))}"
        if news_key not in st.session_state:
            st.session_state[news_key] = None

        if st.session_state[news_key] is None:
            if st.button("🔍 Fetch Latest News", type="primary", use_container_width=True, key="fetch_news_btn"):
                news_loading = st.empty()
                news_loading.markdown(
                    _render_loading_animation(
                        "Notifications.svg",
                        "Fetching the latest news...",
                        f"Scanning the web for recent stories about {dest_name}.",
                    ),
                    unsafe_allow_html=True,
                )
                with st.spinner("Searching for recent news..."):
                    try:
                        news_svc = NewsService()
                        loop = asyncio.new_event_loop()
                        try:
                            digest = loop.run_until_complete(
                                news_svc.collect(
                                    destination=dest_name,
                                    interests=_interests,
                                )
                            )
                        finally:
                            loop.close()
                        news_loading.empty()
                        st.session_state[news_key] = digest
                        st.rerun()
                    except Exception as news_err:
                        news_loading.empty()
                        st.error(f"Failed to fetch news: {news_err}")
        else:
            digest = st.session_state[news_key]

            # Overview card
            if digest.overview:
                overview_html = f"<p style='font-size: 15px; color: #3a3a3c; line-height: 1.6;'>{digest.overview}</p>"
                st.markdown(
                    fluent_card("Overview", "blue", overview_html),
                    unsafe_allow_html=True,
                )

            if not digest.articles:
                st.info("No recent news articles found for this destination.")
            else:
                # Render article cards
                for article in digest.articles:
                    date_str = f" · {article.date}" if article.date else ""
                    source_str = f" · {article.source}" if article.source else ""
                    summary_text = article.summary or article.snippet[:200]
                    summary_html = f"<p style='font-size: 14px; color: #3a3a3c; line-height: 1.5; margin-bottom: 8px;'>{summary_text}</p>"
                    meta_html = (
                        f"<p style='font-size: 12px; color: #6e6e73; margin-bottom: 12px;'>{source_str}{date_str}</p>"
                    )
                    link_html = f"<a href='{article.url}' target='_blank' style='font-size: 13px; color: var(--ms-blue); text-decoration: none; font-weight: 500;'>Read full article →</a>"
                    card_html = (
                        f"<div style='border-bottom: 1px solid #f0f0f0; padding-bottom: 16px; margin-bottom: 16px;'>"
                        f"<h4 style='font-size: 16px; margin-bottom: 8px; color: #1d1d1f;'>{article.title}</h4>"
                        f"{meta_html}{summary_html}{link_html}</div>"
                    )
                    st.markdown(card_html, unsafe_allow_html=True)

            st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
            col1, col2, _ = st.columns([1, 1, 2])
            with col1:
                if st.button("🔄 Refresh News", key="refresh_news_btn"):
                    st.session_state[news_key] = None
                    st.rerun()
            with col2:
                if st.button("🗑️ Clear Cache", key="clear_news_btn"):
                    st.session_state[news_key] = None
                    st.rerun()

            fetched = digest.fetched_at
            if fetched:
                st.caption(f"Last updated: {fetched}")


def run() -> None:
    import sys

    from agentic_tour_planner.config.settings import get_settings

    _settings = get_settings()
    api_host = getattr(_settings, "api_host", "127.0.0.1")
    app_path = Path(__file__).resolve()
    os.execvp(  # noqa: S606 - argv-form execvp (no shell); required to re-launch streamlit in-process
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.port",
            "8501",
            "--server.address",
            api_host,
            "--theme.base",
            "light",
        ],
    )
