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
    PlanningRequest,
    PlanningResponse,
    RetrievedContext,
    TransportOption,
)
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.pipeline.place_constraints import enforce_minimum_daily_spots
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
from agentic_tour_planner.utils.profiler import StageTimer

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
        self.profiler = StageTimer()

        # Use planner model for main itinerary generation
        self.planner_provider, self.planner_model = self.llm_provider.get_planner_model()
        logger.info(f"Initialized pipeline with planner model: {self.planner_provider}/{self.planner_model}")

    async def gather_context(self, request: PlanningRequest) -> RetrievedContext:
        logger.debug(
            f"Gathering context for destination={request.destination!r} "
            f"interests={request.interests} include_live_data={request.include_live_data}"
        )
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
        self.profiler.reset()
        logger.info(
            f"Running pipeline for destination={request.destination!r} "
            f"days={request.trip_length_days} provider={request.provider or 'default'}"
        )

        # ── Phase 1: Independent tasks ──────────────────────────────────
        # Gather Context and Live Web Collection share no data — run concurrently.

        async def _gather_with_events() -> RetrievedContext:
            if context is not None:
                return context
            if emitter:
                emitter.emit(LogEvent(event="step", step="Gather Context", message="Gathering context..."))
            ctx = await self.gather_context(request)
            if emitter:
                emitter.emit(
                    LogEvent(
                        event="debug",
                        step="Gather Context",
                        message="Context gathered",
                        detail={
                            "documents_count": len(ctx.documents),
                            "search_results_count": len(ctx.search_results),
                            "place_hours_count": len(ctx.place_hours),
                        },
                    )
                )
            return ctx

        async with self.profiler.atrack("Gather Context"):
            context_task = asyncio.create_task(_gather_with_events())

        live_task: asyncio.Task | None = None
        if request.include_live_data:

            async def _live_collect() -> LiveWebBrief | None:
                async with self.profiler.atrack("Live Web Collection"):
                    logger.info("Collecting live web intelligence.")
                    return await self.live_collector.collect(request, provider_override=request.provider)

            live_task = asyncio.create_task(_live_collect())

        # Wait for context (needed for insights)
        if context is None:
            context = await context_task
        else:
            logger.debug("Reusing supplied context.")
            await context_task  # still wait if it was created

        # ── Phase 2: Build insights (needs context) ─────────────────────
        async with self.profiler.atrack("Build Insights"):
            if insights is None:
                if emitter:
                    emitter.emit(LogEvent(event="step", step="Build Insights", message="Building insights..."))
                insights = await self.insights_builder.build(request, context, provider_override=request.provider)
                if emitter:
                    emitter.emit(
                        LogEvent(
                            event="debug",
                            step="Build Insights",
                            message="Insights built",
                            detail={
                                "route_strategy_preview": insights.route.strategy[:80] if insights.route.strategy else "",
                                "budget_estimate": insights.budget.estimated_daily_budget if insights.budget else None,
                            },
                        )
                    )
            else:
                logger.debug("Reusing supplied insights.")

        # ── Phase 3: Wait for live data (ran in parallel with Phase 1+2) ──
        live_brief: LiveWebBrief | None = None
        if live_task:
            live_brief = await live_task
            if live_brief and live_brief.sources:
                async with self.profiler.atrack("Live Web Collection"):
                    ph = []
                    for src in live_brief.sources[:3]:
                        ph.append(await lookup_opening_hours(src.title, request.destination))
                    context.place_hours = ph

        # ── Phase 4: Build prompt + generate plan ───────────────────────
        async with self.profiler.atrack("Build Prompt"):
            prompt = build_itinerary_prompt(request, context, insights, live_web_brief=live_brief)
            logger.debug(f"Built planning prompt (length={len(prompt)} chars).")

        async with self.profiler.atrack("Generate Plan"):
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

        # ── Phase 5: Parallel post-processing ───────────────────────────
        # Cost Estimate is expensive (~115s or ~10s with agnes); run it
        # concurrent with cheap parse/transform steps.

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
        logger.info(f"Planner: {planner_provider}/{planner_model}  |  Worker: {worker_provider}/{worker_model}")

        async def _cost_estimate() -> CostEstimate | None:
            try:
                async with self.profiler.atrack("Cost Estimate"):
                    return await self.cost_estimator.estimate(request, plan_json)
            except Exception as e:
                logger.error(f"Cost estimation failed: {e}")
                return None

        cost_task = asyncio.create_task(_cost_estimate())

        # Cheap steps inline (milliseconds each)
        async with self.profiler.atrack("Build Citations"):
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

        async with self.profiler.atrack("Parse Itinerary"):
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
            itinerary = enforce_minimum_daily_spots(request, itinerary)
            logger.debug(f"Parsed {len(itinerary)} itinerary days.")

        async with self.profiler.atrack("Transport Options"):
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

        # Await cost estimate (ran in background)
        cost_estimate = await cost_task

        logger.info(f"Pipeline complete for {request.destination!r}.")
        if emitter:
            emitter.emit(
                LogEvent(
                    event="metric",
                    step="Generate Plan",
                    message="Plan generated",
                    detail={
                        "provider": planner_provider,
                        "model": planner_model,
                    },
                )
            )
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
        async with self.profiler.atrack("Detailed Places: Gather"):
            names: list[str] = []
            seen: set[str] = set()
            for day in getattr(base_response, "itinerary", []):
                for s in getattr(day, "spots", None) or []:
                    n = s.name if not isinstance(s, dict) else s.get("name")
                    if n and n not in seen:
                        seen.add(n)
                        names.append(n)

        async with self.profiler.atrack("Detailed Places: Opening Hours"):
            place_hours_map: dict[str, dict] = {}
            if names:
                logger.info(f"Fetching real opening hours for {len(names)} places via Google Places")
                results = await asyncio.gather(*[lookup_opening_hours(n, request.destination) for n in names])
                for n, ph in zip(names, results, strict=False):
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

        async with self.profiler.atrack("Detailed Places: LLM Generation"):
            live_brief = getattr(base_response, "live_web_brief", None)
            prompt = build_detailed_places_prompt(request, base_response, live_brief, place_hours_map, insights)
            raw = await self.llm_provider.complete_json(prompt, request, system_prompt=DETAILED_SYSTEM_PROMPT)
        detailed: DetailedPlan | None = None
        if raw and isinstance(raw, dict) and raw.get("days"):
            try:
                detailed = DetailedPlan.model_validate(raw)
            except Exception as exc:
                logger.warning(f"Detailed places JSON parse failed: {exc}")
                detailed = None
        else:
            logger.warning("Detailed places generation returned no usable 'days'.")
        return detailed

    def _fallback_plan(self, request: PlanningRequest) -> dict:
        """Generate a basic plan when LLM fails."""
        logger.debug(f"Generating fallback plan for {request.destination!r} days={request.trip_length_days}")
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
