from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agentic_tour_planner.domain.models import PlanningInsights, PlanningRequest, RetrievedContext
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.pipeline.prompts import build_itinerary_prompt
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder


class PlannerGraphState(TypedDict, total=False):
    request: PlanningRequest
    context: RetrievedContext
    insights: PlanningInsights
    prompt: str
    plan_json: dict


def build_planner_graph(
    gather_context: Callable[[PlanningRequest], Awaitable[RetrievedContext]],
    llm_provider: LLMProvider,
    insights_builder: PlanningInsightsBuilder,
):
    async def gather_context_node(state: PlannerGraphState):
        return {"context": await gather_context(state["request"])}

    async def build_insights_node(state: PlannerGraphState):
        return {"insights": insights_builder.build(state["request"], state["context"])}

    async def build_prompt_node(state: PlannerGraphState):
        return {"prompt": build_itinerary_prompt(state["request"], state["context"], state["insights"])}

    async def generate_plan_node(state: PlannerGraphState):
        return {"plan_json": await llm_provider.complete_json(state["prompt"], state["request"])}

    workflow = StateGraph(PlannerGraphState)
    workflow.add_node("gather_context", gather_context_node)
    workflow.add_node("build_insights", build_insights_node)
    workflow.add_node("build_prompt", build_prompt_node)
    workflow.add_node("generate_plan", generate_plan_node)
    workflow.set_entry_point("gather_context")
    workflow.add_edge("gather_context", "build_insights")
    workflow.add_edge("build_insights", "build_prompt")
    workflow.add_edge("build_prompt", "generate_plan")
    workflow.add_edge("generate_plan", END)
    return workflow.compile()

