from __future__ import annotations

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import (
    Citation,
    DayPlan,
    PlanningRequest,
    PlanningResponse,
    RetrievedContext,
)
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.pipeline.graph import build_planner_graph
from agentic_tour_planner.retrieval.reranker import HybridReranker
from agentic_tour_planner.retrieval.vector_store import VectorStore
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder
from agentic_tour_planner.tools.place_intel import PlaceIntelTool
from agentic_tour_planner.tools.weather import WeatherTool
from agentic_tour_planner.tools.web_search import WebSearchTool


class AgenticTourPlannerPipeline:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.settings = get_settings()
        self.llm_provider = provider or LLMProvider()
        self.vector_store = VectorStore()
        self.reranker = HybridReranker()
        self.search_tool = WebSearchTool()
        self.place_tool = PlaceIntelTool()
        self.weather_tool = WeatherTool()
        self.insights_builder = PlanningInsightsBuilder()
        self.graph = build_planner_graph(self.gather_context, self.llm_provider, self.insights_builder)

    async def gather_context(self, request: PlanningRequest) -> RetrievedContext:
        query = " ".join([request.destination, *request.interests, request.notes or ""]).strip()
        docs = self.vector_store.retrieve(query=query, top_k=self.settings.retrieval_top_k)
        docs = self.reranker.rerank(query, docs, top_k=self.settings.rerank_top_k)
        search_results = self.search_tool.suggest_places(request.destination, request.interests) if request.include_live_data else []
        place_hours = []
        for result in search_results[: min(2, len(search_results))]:
            place_hours.append(await self.place_tool.lookup_opening_hours(result.title, request.destination))
        weather = await self.weather_tool.current_weather(request.destination) if request.include_live_data else None
        return RetrievedContext(documents=docs, search_results=search_results, place_hours=place_hours, weather=weather)

    async def run(self, request: PlanningRequest) -> PlanningResponse:
        state = await self.graph.ainvoke({"request": request})
        provider, model = self.llm_provider.resolve_provider(request)
        insights = self.insights_builder.build(request, state["context"])
        plan_json = state["plan_json"]
        citations = [
            Citation(
                title=citation.get("title", "Reference"),
                url=citation.get("url", "https://example.local"),
                note=citation.get("note"),
            )
            for citation in plan_json.get("citations", [])
        ]
        if not citations:
            citations = [
                Citation(title=document.title, url=document.url or "https://example.local")
                for document in state["context"].documents[:5]
                if document.url
            ]
        itinerary = [DayPlan.model_validate(item) for item in plan_json.get("itinerary", [])]
        return PlanningResponse(
            overview=plan_json.get("overview", f"Trip plan for {request.destination}"),
            itinerary=itinerary,
            practical_tips=plan_json.get("practical_tips", []),
            citations=citations,
            insights=insights,
            provider_used=provider,
            model_used=model,
        )

