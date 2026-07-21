from __future__ import annotations

import asyncio
import re
from typing import Any

from agentic_tour_planner.api.events import EventEmitter
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import (
    Citation,
    CostEstimate,
    DayPlan,
    DetailedPlan,
    LiveWebBrief,
    LogEvent,
    PlanningInsights,
    PlanningRequest,
    PlanningResponse,
    RetrievedContext,
    TransportOption,
)
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.pipeline.prompts import (
    DETAILED_SYSTEM_PROMPT,
    build_detailed_places_prompt,
    build_itinerary_prompt,
)
from agentic_tour_planner.retrieval.hybrid_retriever import HybridRetriever
from agentic_tour_planner.retrieval.reranker import rerank_documents
from agentic_tour_planner.services.cost_estimator import CostEstimator
from agentic_tour_planner.services.live_web_collector import LiveWebCollector
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder
from agentic_tour_planner.tools.place_intel import lookup_opening_hours
from agentic_tour_planner.tools.weather import WeatherTool
from agentic_tour_planner.tools.web_search import WebSearchTool
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class AgenticTourPlannerPipeline:
    def __init__(self, provider=None) -> None:
        self.settings = get_settings()
        self.llm_provider = LLMProvider()
        self.retriever = HybridRetriever()
        self.search_tool = WebSearchTool()
        self.weather_tool = WeatherTool()
        self.insights_builder = PlanningInsightsBuilder()
        self.cost_estimator = CostEstimator()
        self.live_collector = LiveWebCollector(self.llm_provider)

        # Use planner model for main itinerary generation
        self.planner_provider, self.planner_model = self.llm_provider.get_planner_model()
        logger.info(f"Initialized pipeline with planner model: {self.planner_provider}/{self.planner_model}")

    async def gather_context(self, request: PlanningRequest) -> RetrievedContext:
        logger.debug(f"Gathering context for destination={request.destination!r} "
                     f"interests={request.interests} include_live_data={request.include_live_data}")
        query = " ".join([request.destination, *request.interests, request.notes or ""]).strip()
        docs = self.retriever.retrieve(query=query, top_k=self.settings.retrieval_top_k)
        docs = rerank_documents(query, docs, top_k=self.settings.rerank_top_k)
        # Live web search (DDGS suggest_places) is replaced by the on-the-fly
        # LiveWebCollector (blogs/videos crawl + translate) run in `run()`. The
        # knowledge base (docs) remains the supplementary retrieval source here.
        search_results: list = []
        place_hours: list = []
        weather = await self.weather_tool.current_weather(request.destination) if request.include_live_data else None
        logger.debug(f"Retrieved {len(docs)} documents; weather={'present' if weather else 'none'}")
        return RetrievedContext(documents=docs, search_results=search_results, place_hours=place_hours, weather=weather)

    async def run(
        self,
        request: PlanningRequest,
        context: RetrievedContext | None = None,
        insights: Any | None = None,
        emitter: EventEmitter | None = None,
    ) -> PlanningResponse:
        logger.info(f"Running pipeline for destination={request.destination!r} "
                    f"days={request.trip_length_days} provider={request.provider or 'default'}")
        # Step 1: Gather context (reuse a pre-built context when the caller already
        # has one, e.g. the CLI which builds it once with the chosen provider).
        if context is None:
            if emitter:
                emitter.emit(LogEvent(event="step", step="Gather Context", message="Gathering context..."))
            context = await self.gather_context(request)
            if emitter:
                emitter.emit(LogEvent(event="debug", step="Gather Context", message="Context gathered", detail={
                    "documents_count": len(context.documents),
                    "search_results_count": len(context.search_results),
                    "place_hours_count": len(context.place_hours),
                }))
        else:
            logger.debug("Reusing supplied context.")

        # Step 2: Build insights using worker agents (lightweight models). Reuse a
        # pre-built insights object if supplied; otherwise build with the selected
        # provider so the worker calls honour the user's provider selection.
        if insights is None:
            if emitter:
                emitter.emit(LogEvent(event="step", step="Build Insights", message="Building insights..."))
            insights = await self.insights_builder.build(
                request, context, provider_override=request.provider
            )
            if emitter:
                emitter.emit(LogEvent(event="debug", step="Build Insights", message="Insights built", detail={
                    "route_strategy_preview": insights.route.strategy[:80] if insights.route.strategy else "",
                    "budget_estimate": insights.budget.estimated_daily_budget if insights.budget else None,
                }))
        else:
            logger.debug("Reusing supplied insights.")

        # Step 2.5: On-the-fly live web intelligence (blogs/videos crawl + translate).
        # This is the authoritative source of truth fed to the planner; nothing is
        # stored in the knowledge base.
        live_brief: LiveWebBrief | None = None
        if request.include_live_data:
            logger.info("Collecting live web intelligence.")
            live_brief = await self.live_collector.collect(request, provider_override=request.provider)
            if live_brief and live_brief.sources:
                # Seed opening-hours lookup from the real places found in live sources.
                ph = []
                for src in live_brief.sources[:3]:
                    ph.append(await lookup_opening_hours(src.title, request.destination))
                context.place_hours = ph
                logger.debug(f"Looked up opening hours for {len(ph)} live sources.")

        # Step 3: Build the planning prompt
        prompt = build_itinerary_prompt(request, context, insights, live_web_brief=live_brief)
        logger.debug(f"Built planning prompt (length={len(prompt)} chars).")

        # Step 4: Generate plan using planner agent (heavy model)
        if emitter:
            emitter.emit(LogEvent(event="step", step="Generate Plan", message="Generating plan..."))
        try:
            plan_json = await self.llm_provider.complete_json(prompt, request)
            if not plan_json:
                logger.warning("Planner returned empty result; using fallback plan.")
                plan_json = self._fallback_plan(request)
        except Exception as e:
            logger.error(f"Planner failed, using fallback: {e}")
            plan_json = self._fallback_plan(request)

        # Resolve the provider/model that actually produced each role's output.
        planner_provider, planner_model = self.llm_provider.last_planner_used()
        worker_meta = self.insights_builder.last_worker_used
        worker_used = {v for v in worker_meta.values() if v}
        if not worker_used:
            worker_provider, worker_model = "fallback", "heuristic"
        elif len(worker_used) == 1:
            worker_provider, worker_model = next(iter(worker_used))
        else:
            worker_provider = ",".join(sorted({p for p, _ in worker_used}))
            worker_model = ",".join(sorted({m for _, m in worker_used}))
        logger.info(
            f"Planner: {planner_provider}/{planner_model}  |  "
            f"Worker: {worker_provider}/{worker_model}"
        )

        # Step 5: Build citations (robust to either list-of-strings or list-of-dicts)
        raw_citations = plan_json.get("citations", []) or []
        normalized_citations: list[dict] = []
        for citation in raw_citations:
            if isinstance(citation, dict):
                normalized_citations.append(citation)
            else:
                normalized_citations.append({"title": str(citation), "url": "https://example.local"})
        citations = [
            Citation(
                title=c.get("title", "Reference"),
                url=c.get("url", "https://example.local"),
                note=c.get("note"),
            )
            for c in normalized_citations
        ]
        if not citations:
            citations = [
                Citation(title=document.title, url=document.url or "https://example.local")
                for document in context.documents[:5]
                if document.url
            ]
        logger.debug(f"Resolved {len(citations)} citations.")

        # Step 6: Parse itinerary (robust to schema drift from the planner model)
        raw_itinerary = plan_json.get("itinerary", []) or []
        itinerary = []
        for item in raw_itinerary:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            day = item.get("day")
            if isinstance(day, str):
                m = re.search(r"\d+", day)
                item["day"] = int(m.group()) if m else len(itinerary) + 1
            elif not isinstance(day, int):
                item["day"] = len(itinerary) + 1
            for field in ("morning", "afternoon", "evening", "meals", "logistics"):
                value = item.get(field)
                if value is None:
                    item[field] = []
                elif isinstance(value, str):
                    item[field] = [value]
            itinerary.append(DayPlan.model_validate(item))
        logger.debug(f"Parsed {len(itinerary)} itinerary days.")

        # Step 7: Transport options (top-level, when public transport is relevant)
        raw_transport = plan_json.get("transport_options", []) or []
        transport_options = [
            TransportOption(
                mode=t.get("mode", "transport"),
                description=t.get("description"),
                fare=t.get("fare"),
                notes=t.get("notes"),
            )
            for t in raw_transport
            if isinstance(t, dict)
        ]

        # Step 8: Cost estimate (LLM calls the calculator tool for step-by-step math)
        cost_estimate: CostEstimate | None = None
        try:
            cost_estimate = await self.cost_estimator.estimate(request, plan_json)
        except Exception as e:
            logger.error(f"Cost estimation failed: {e}")

        logger.info(f"Pipeline complete for {request.destination!r}.")
        if emitter:
            emitter.emit(LogEvent(event="metric", step="Generate Plan", message="Plan generated", detail={
                "provider": planner_provider,
                "model": planner_model,
            }))
        return PlanningResponse(
            overview=plan_json.get("overview", f"Trip plan for {request.destination}"),
            itinerary=itinerary,
            practical_tips=plan_json.get("practical_tips", []),
            citations=citations,
            insights=insights,
            provider_used=planner_provider,
            model_used=planner_model,
            monthly_weather=plan_json.get("monthly_weather"),
            transport_options=transport_options,
            cost_estimate=cost_estimate,
            live_web_brief=live_brief,
            worker_provider_used=worker_provider,
            worker_model_used=worker_model,
        )

    async def run_detailed_places(
        self,
        request: PlanningRequest,
        base_response: Any,
        context: RetrievedContext | None = None,
        insights: Any | None = None,
    ) -> DetailedPlan | None:
        """Generate the detailed, place-by-place itinerary as structured data.

        Reuses the standard plan's chosen core places, pre-fetches their REAL
        opening hours via the Google Places tool, then asks the LLM to emit the
        fixed ``output_format.md`` JSON contract.
        """
        logger.info(f"Building detailed places itinerary for {request.destination!r}")
        # Collect unique core place names from the standard plan's spots.
        names: list[str] = []
        seen: set[str] = set()
        for day in getattr(base_response, "itinerary", []):
            for s in getattr(day, "spots", None) or []:
                n = s.name if not isinstance(s, dict) else s.get("name")
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)

        # Pre-fetch REAL opening hours via the Google Places tool (parallelised).
        place_hours_map: dict[str, dict] = {}
        if names:
            logger.info(f"Fetching real opening hours for {len(names)} places via Google Places")
            results = await asyncio.gather(
                *[lookup_opening_hours(n, request.destination) for n in names]
            )
            for n, ph in zip(names, results):
                if ph is None:
                    place_hours_map[n] = {"status": "unavailable", "opening_hours": []}
                elif isinstance(ph, dict):
                    place_hours_map[n] = ph
                else:
                    place_hours_map[n] = {
                        "status": getattr(ph, "status", None),
                        "opening_hours": list(getattr(ph, "opening_hours", None) or []),
                    }
            logger.debug(f"Fetched opening hours for {len(place_hours_map)} places.")

        live_brief = getattr(base_response, "live_web_brief", None)
        prompt = build_detailed_places_prompt(
            request, base_response, live_brief, place_hours_map, insights
        )
        raw = await self.llm_provider.complete_json(
            prompt, request, system_prompt=DETAILED_SYSTEM_PROMPT
        )
        detailed: DetailedPlan | None = None
        if raw and isinstance(raw, dict) and raw.get("days"):
            try:
                detailed = DetailedPlan.model_validate(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Detailed places JSON parse failed: {exc}")
                detailed = None
        else:
            logger.warning("Detailed places generation returned no usable 'days'.")
        return detailed

    def _fallback_plan(self, request: PlanningRequest) -> dict:
        """Generate a basic plan when LLM fails."""
        logger.debug(f"Generating fallback plan for {request.destination!r} "
                     f"days={request.trip_length_days}")
        days = []
        interests = request.interests or ["landmarks", "food", "walks"]
        for day in range(1, request.trip_length_days + 1):
            theme = interests[(day - 1) % len(interests)].title()
            days.append(
                {
                    "day": day,
                    "theme": f"{theme} in {request.destination}",
                    "morning": [f"Explore a {theme.lower()} anchor area."],
                    "afternoon": [f"Visit a second {theme.lower()} venue and lunch nearby."],
                    "evening": ["Wrap with a scenic walk and local dinner."],
                    "meals": ["Breakfast near hotel", "Lunch in activity zone", "Dinner in lively district"],
                    "logistics": ["Use one neighborhood cluster per half day."],
                }
            )
        return {
            "overview": f"A {request.trip_length_days}-day {request.destination} itinerary balanced around {', '.join(interests)}.",
            "itinerary": days,
            "practical_tips": [
                "Reconfirm hours for reservation-heavy attractions.",
                "Keep weather-flexible indoor alternatives ready.",
            ],
            "citations": [],
        }