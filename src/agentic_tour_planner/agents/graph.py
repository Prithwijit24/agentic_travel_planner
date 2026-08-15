"""LangGraph critique loop wiring.

Nodes: cost_agent -> budget_agent -> timing_agent -> should_revise?
    yes (critiques AND revision_count < 2) -> planner_agent -> cost_agent
    no -> END
"""

from __future__ import annotations

from typing import Any, cast

from langgraph.graph import END, StateGraph
from loguru import logger

from agentic_tour_planner.agents.budget_agent import critique_budget
from agentic_tour_planner.agents.cost_agent import estimate_cost
from agentic_tour_planner.agents.planner_agent import resolve_critiques
from agentic_tour_planner.agents.state import TripState
from agentic_tour_planner.agents.timing_agent import critique_timing
from agentic_tour_planner.config.settings import get_settings


def _max_revisions():
    return get_settings().pipeline_max_revisions


def _should_revise(state: TripState) -> str:
    """Conditional edge: decide whether to revise or end."""
    max_revisions = _max_revisions()
    critiques = state.get("critiques", [])
    revision_count = state.get("revision_count", 0)

    if critiques and revision_count < max_revisions:
        logger.info(f"Revising (iteration {revision_count + 1}/{max_revisions}): {len(critiques)} critiques pending")
        return "revise"
    if critiques and revision_count >= max_revisions:
        logger.info(f"Max revisions reached ({max_revisions}), passing {len(critiques)} critiques as known limitations")
    return "end"


def _add_known_limitations(state: TripState) -> TripState:
    """Move surviving critiques to known_limitations before END."""
    max_revisions = _max_revisions()
    critiques = state.get("critiques", [])
    revision_count = state.get("revision_count", 0)
    if critiques and revision_count >= max_revisions:
        limitations = list(state.get("known_limitations", []))
        limitations.extend(critiques)
        return {**state, "known_limitations": limitations}
    return {**state, "known_limitations": state.get("known_limitations", [])}


def build_graph() -> Any:
    """Build and compile the LangGraph critique loop."""
    graph = StateGraph(TripState)

    graph.add_node("cost_agent", estimate_cost)
    graph.add_node("budget_agent", critique_budget)
    graph.add_node("timing_agent", critique_timing)
    graph.add_node("planner_agent", resolve_critiques)
    graph.add_node("add_known_limitations", _add_known_limitations)

    graph.set_entry_point("cost_agent")
    graph.add_edge("cost_agent", "budget_agent")
    graph.add_edge("budget_agent", "timing_agent")
    graph.add_conditional_edges(
        "timing_agent",
        _should_revise,
        {"revise": "planner_agent", "end": "add_known_limitations"},
    )
    graph.add_edge("planner_agent", "cost_agent")
    graph.add_edge("add_known_limitations", END)

    return graph.compile()


async def run_critique_loop(state: TripState) -> TripState:
    """Run the critique loop to completion."""
    app = build_graph()
    return cast(TripState, await app.ainvoke(state))
