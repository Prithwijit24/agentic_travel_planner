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
    LogEvent,
    PlaceHours,
    PlanningInsights,
    PlanningRequest,
    PlanningResponse,
    RetrievedContext,
    SearchResult,
    SourceDocument,
    TransportOption,
)
from agentic_tour_planner.llm.provider import LLMProvider, LLMUnavailableError
from agentic_tour_planner.pipeline.place_constraints import enforce_minimum_daily_spots
from agentic_tour_planner.pipeline.prompts import (
    DETAILED_SYSTEM_PROMPT,
    build_detailed_places_prompt,
    build_itinerary_prompt,
)
from agentic_tour_planner.services.cost_estimator import CostEstimator
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder
from agentic_tour_planner.tools.ai_stack_client import AiStackClient
from agentic_tour_planner.tools.weather import WeatherTool
from agentic_tour_planner.utils.logging import get_logger
from agentic_tour_planner.utils.profiler import StageTimer

logger = get_logger(__name__)


class AgenticTourPlannerPipeline:
    def __init__(self, provider=None) -> None:
        self.settings = get_settings()
        self.llm_provider = LLMProvider()
        self.ai_stack = AiStackClient()
        self.weather_tool = WeatherTool()
        self.insights_builder = PlanningInsightsBuilder()
        self.cost_estimator = CostEstimator()
        self.profiler = StageTimer()
        self._context_summary: dict | None = None
        self._context: RetrievedContext | None = None

        # Use planner model for main itinerary generation
        self.planner_provider, self.planner_model = self.llm_provider.get_planner_model()
        logger.info(f"Initialized pipeline with planner model: {self.planner_provider}/{self.planner_model}")

    @property
    def context_summary(self) -> dict | None:
        return self._context_summary

    @property
    def context(self) -> RetrievedContext | None:
        return self._context

    async def gather_context(self, request: PlanningRequest) -> RetrievedContext:
        """Gather context using AI Infra Stack pipeline."""
        logger.debug(
            f"Gathering context for destination={request.destination!r} "
            f"interests={request.interests} include_live_data={request.include_live_data}"
        )
        query = " ".join([request.destination, *request.interests, request.notes or ""]).strip()

        # Use AI Infra Stack pipeline for search + crawl + rerank
        docs: list[SourceDocument] = []
        search_results: list[SearchResult] = []
        try:
            stack_result = await self.ai_stack.pipeline(
                query=query,
                top_k=self.settings.retrieval_top_k or 5,
                crawl_limit=10,
                max_search_results=15,
            )
            # Convert stack results to SourceDocument objects
            for item in stack_result.get("results", []):
                content = item.get("markdown", item.get("content", ""))
                if content:
                    docs.append(
                        SourceDocument(
                            source_id=item.get("url", ""),
                            source_type="web",
                            title=item.get("title", ""),
                            content=content,
                            url=item.get("url", ""),
                            metadata={"score": item.get("score", 0.0)},
                        )
                    )
        except Exception as e:
            logger.warning(f"AI Infra Stack pipeline failed, using empty results: {e}")

        # Get weather if requested
        weather = await self.weather_tool.current_weather(request.destination) if request.include_live_data else None

        logger.debug(f"Retrieved {len(docs)} documents; weather={'present' if weather else 'none'}")
        self._context_summary = {
            "documents_count": len(docs),
            "weather": weather.summary if weather else None,
        }
        ctx = RetrievedContext(documents=docs, search_results=search_results, place_hours=[], weather=weather)
        self._context = ctx
        return ctx

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

        # ── Phase 1: Gather Context ──────────────────────────────────────
        async with self.profiler.atrack("Gather Context"):
            if emitter:
                emitter.emit(LogEvent(event="step", step="Gather Context", message="Gathering context..."))
            if context is None:
                context = await self.gather_context(request)
            else:
                logger.debug("Reusing supplied context.")
            if emitter:
                emitter.emit(
                    LogEvent(
                        event="debug",
                        step="Gather Context",
                        message="Context gathered",
                        detail={
                            "documents_count": len(context.documents),
                        },
                    )
                )

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
                                "route_strategy_preview": insights.route.strategy[:80]
                                if insights.route.strategy
                                else "",
                                "budget_estimate": insights.budget.estimated_daily_budget if insights.budget else None,
                            },
                        )
                    )
            else:
                logger.debug("Reusing supplied insights.")

        # ── Phase 3: Build prompt + generate plan ───────────────────────
        async with self.profiler.atrack("Build Prompt"):
            prompt = build_itinerary_prompt(request, context, insights)
            logger.debug(f"Built planning prompt (length={len(prompt)} chars).")

        async with self.profiler.atrack("Generate Plan"):
            if emitter:
                emitter.emit(LogEvent(event="step", step="Generate Plan", message="Generating plan..."))
            try:
                plan_json = await self.llm_provider.complete_json(
                    prompt,
                    request,
                )
                if not plan_json:
                    logger.warning("Planner returned empty result; using fallback plan.")
                    plan_json = self._fallback_plan(request)
            except LLMUnavailableError:
                raise
            except Exception as e:
                logger.error(f"Planner failed, using fallback: {e}")
                plan_json = self._fallback_plan(request)

        # ── Phase 4: Parallel post-processing ───────────────────────────
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
            itinerary: list[DayPlan] = []
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
            live_web_brief=None,
            worker_provider_used=worker_provider,
            worker_model_used=worker_model,
        )

    async def run_detailed_places(
        self,
        request: PlanningRequest,
        base_response: Any,
        context: RetrievedContext | None = None,
        insights: PlanningInsights | None = None,
    ) -> DetailedPlan | None:
        """Generate the detailed, place-by-place itinerary as structured data."""
        if insights is None:
            raise RuntimeError("insights are required for detailed places generation")
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

        async with self.profiler.atrack("Detailed Places: Search"):
            place_hours_map: dict[str, PlaceHours] = {}
            if names:
                logger.info(f"Fetching info for {len(names)} places via AI Infra Stack")

                sem = asyncio.Semaphore(5)

                async def _fetch(name: str) -> None:
                    async with sem:
                        try:
                            result = await self.ai_stack.search(
                                query=f"{name} {request.destination} opening hours",
                                max_results=3,
                            )
                            if result and result.get("results"):
                                info = result["results"][0]
                                place_hours_map[name] = PlaceHours(
                                    venue=name,
                                    status="found",
                                    opening_hours=[info.get("snippet", "")],
                                    source=info.get("url", ""),
                                )
                        except Exception as e:
                            logger.warning(f"Failed to search for {name}: {e}")
                            place_hours_map[name] = PlaceHours(venue=name, status="unavailable")

                await asyncio.gather(*(_fetch(n) for n in names[:5]))  # Limit to avoid rate limits
                logger.debug(f"Fetched info for {len(place_hours_map)} places.")

        async with self.profiler.atrack("Detailed Places: LLM Generation"):
            live_brief = getattr(base_response, "live_web_brief", None)
            itinerary = list(getattr(base_response, "itinerary", []))
            day_numbers = [getattr(d, "day", i + 1) for i, d in enumerate(itinerary)] or [1]

            # Generate each day in parallel (each call returns only its own day),
            # then merge. This turns a single ~350s serial generation into roughly
            # one-day latency when the provider supports concurrent requests.
            concurrency = max(1, min(4, len(day_numbers)))

            async def _gen_day(day_num: int) -> dict | None:
                prompt = build_detailed_places_prompt(
                    request, base_response, live_brief, place_hours_map, insights, target_day=day_num
                )
                try:
                    return await self.llm_provider.complete_json(
                        prompt,
                        request,
                        system_prompt=DETAILED_SYSTEM_PROMPT,
                    )
                except Exception as exc:
                    logger.warning(f"Detailed places generation failed for day {day_num}: {exc}")
                    return None

            semaphore = asyncio.Semaphore(concurrency)

            async def _guarded(day_num: int) -> dict | None:
                async with semaphore:
                    return await _gen_day(day_num)

            raw_days_list = await asyncio.gather(*(_guarded(d) for d in day_numbers))
            raw: dict[str, list[dict]] = {"days": []}
            for day_num, day_raw in zip(day_numbers, raw_days_list, strict=False):
                if not isinstance(day_raw, dict):
                    continue
                found = [d for d in (day_raw.get("days") or []) if isinstance(d, dict)]
                if not found:
                    logger.warning(f"Detailed places: day {day_num} returned no usable days.")
                    continue
                raw["days"].append(found[0])
            if raw["days"]:
                raw["days"].sort(key=lambda d: int(d.get("day", 0) or 0))
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
