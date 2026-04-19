from __future__ import annotations

import httpx
import os
import sys
import streamlit as st

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import PlanningRequest


def _api_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(base_url=settings.api_base_url, timeout=settings.request_timeout_seconds * 3)


def _load_health() -> dict:
    with _api_client() as client:
        response = client.get("/health")
        response.raise_for_status()
        return response.json()


def _create_plan(request: PlanningRequest) -> dict:
    with _api_client() as client:
        response = client.post("/plans", json=request.model_dump(mode="json"))
        response.raise_for_status()
        return response.json()


def _list_plans(limit: int = 10) -> list[dict]:
    with _api_client() as client:
        response = client.get("/plans", params={"limit": limit})
        response.raise_for_status()
        return response.json()


def _list_sources(limit: int = 10) -> list[dict]:
    with _api_client() as client:
        response = client.get("/sources", params={"limit": limit})
        response.raise_for_status()
        return response.json()


def _submit_feedback(plan_id: str, rating: int, comments: str) -> None:
    with _api_client() as client:
        response = client.post("/feedback", json={"plan_id": plan_id, "rating": rating, "comments": comments or None})
        response.raise_for_status()


def _render_header() -> None:
    st.title("Agentic Travel Planner")
    st.caption("Agentic travel design over FastAPI, retrieval, planning workers, and a live knowledge base.")
    try:
        health = _load_health()
        st.success(f"API connected • env={health['env']}")
    except Exception as exc:
        st.error(f"API unavailable: {exc}")


def _render_sidebar() -> tuple[str, str, int, str, bool, int]:
    with st.sidebar:
        st.subheader("Planner Controls")
        provider = st.selectbox("LLM provider", ["openai", "google", "ollama", "openrouter", "xai"])
        model = st.text_input("Model", value="gpt-4o-mini")
        trip_length_days = st.slider("Trip length", min_value=1, max_value=14, value=4)
        budget_level = st.selectbox("Budget", ["budget", "midrange", "luxury"])
        include_live_data = st.toggle("Include live web data", value=True)
        max_attractions_per_day = st.slider("Attractions per day", min_value=1, max_value=6, value=4)
        st.divider()
        st.caption(f"Backend API: `{get_settings().api_base_url}`")
    return provider, model, trip_length_days, budget_level, include_live_data, max_attractions_per_day


def _render_plan_response(response: dict) -> None:
    st.subheader("Overview")
    st.write(response["overview"])

    insights = response["insights"]
    route_col, budget_col, timing_col = st.columns(3)
    with route_col:
        st.markdown("**Route**")
        st.write(insights["route"]["strategy"])
        for item in insights["route"]["cluster_advice"]:
            st.caption(item)
    with budget_col:
        st.markdown("**Budget**")
        st.metric("Daily", f"{insights['budget']['estimated_daily_budget']:.0f}")
        st.metric("Total", f"{insights['budget']['estimated_total_budget']:.0f}")
    with timing_col:
        st.markdown("**Timing**")
        st.write(insights["timing"]["booking_window"])
        st.caption(insights["timing"]["season_summary"])

    st.subheader("Itinerary")
    for day in response["itinerary"]:
        with st.container(border=True):
            st.markdown(f"### Day {day['day']}: {day['theme']}")
            left, right = st.columns(2)
            with left:
                st.write("Morning")
                for item in day["morning"]:
                    st.markdown(f"- {item}")
                st.write("Afternoon")
                for item in day["afternoon"]:
                    st.markdown(f"- {item}")
            with right:
                st.write("Evening")
                for item in day["evening"]:
                    st.markdown(f"- {item}")
                st.write("Meals")
                for item in day["meals"]:
                    st.markdown(f"- {item}")
            if day["logistics"]:
                st.write("Logistics")
                for item in day["logistics"]:
                    st.markdown(f"- {item}")

    if response["practical_tips"]:
        st.subheader("Practical Tips")
        for tip in response["practical_tips"]:
            st.markdown(f"- {tip}")

    if response["citations"]:
        st.subheader("Citations")
        for citation in response["citations"]:
            st.markdown(f"- [{citation['title']}]({citation['url']})")


def _render_feedback(plan_id: str) -> None:
    with st.form("feedback-form"):
        st.subheader("Feedback")
        rating = st.slider("Rating", min_value=1, max_value=5, value=4)
        comments = st.text_area("Comments", value="")
        submitted = st.form_submit_button("Submit feedback")
        if submitted:
            _submit_feedback(plan_id, rating, comments)
            st.success("Feedback recorded.")


def main() -> None:
    st.set_page_config(page_title="Agentic Travel Planner", layout="wide")
    _render_header()
    provider, model, trip_length_days, budget_level, include_live_data, max_attractions_per_day = _render_sidebar()

    planner_tab, plans_tab, sources_tab = st.tabs(["Plan Trip", "Recent Plans", "Knowledge Sources"])

    with planner_tab:
        with st.form("planner-form"):
            hero_left, hero_right = st.columns([2, 1])
            with hero_left:
                destination = st.text_input("Destination", value="Kyoto")
                origin = st.text_input("Origin", value="Tokyo")
                interests_text = st.text_input("Interests", value="temples, food, photography")
                notes = st.text_area("Notes", value="Prefer efficient routing and authentic food spots.")
            with hero_right:
                travel_month = st.text_input("Travel month", value="October")
                st.markdown("**Planner mode**")
                st.caption("The UI posts a typed request to FastAPI and renders the stored response.")
            submitted = st.form_submit_button("Generate plan", type="primary", use_container_width=True)

        if submitted:
            request = PlanningRequest(
                destination=destination,
                origin=origin or None,
                trip_length_days=trip_length_days,
                interests=[item.strip() for item in interests_text.split(",") if item.strip()],
                budget_level=budget_level,
                travel_month=travel_month or None,
                notes=notes or None,
                provider=provider,
                model=model,
                include_live_data=include_live_data,
                max_attractions_per_day=max_attractions_per_day,
            )
            with st.spinner("Generating plan via API..."):
                response = _create_plan(request)
            st.session_state["last_plan_response"] = response

        response = st.session_state.get("last_plan_response")
        if response:
            _render_plan_response(response)
            _render_feedback(response["plan_id"])

    with plans_tab:
        st.subheader("Recent Plans")
        try:
            plans = _list_plans(limit=10)
            for record in plans:
                with st.expander(f"{record['destination']} • {record['created_at']}"):
                    st.write(record["response"]["overview"])
                    st.caption(f"Provider: {record['provider_used']} • Model: {record['model_used']}")
        except Exception as exc:
            st.error(f"Failed to load plans: {exc}")

    with sources_tab:
        st.subheader("Knowledge Sources")
        try:
            sources = _list_sources(limit=15)
            for record in sources:
                with st.container(border=True):
                    st.markdown(f"**{record['title']}**")
                    st.caption(f"{record['source_type']} • chunks={record['chunk_count']} • destination={record['destination'] or 'global'}")
                    if record.get("url"):
                        st.markdown(f"[Open source]({record['url']})")
        except Exception as exc:
            st.error(f"Failed to load sources: {exc}")


if __name__ == "__main__":
    main()


def run() -> None:
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/agentic_tour_planner/app/streamlit_app.py",
            "--server.port",
            str(get_settings().streamlit_server_port),
            "--server.address",
            "0.0.0.0",
        ],
    )
