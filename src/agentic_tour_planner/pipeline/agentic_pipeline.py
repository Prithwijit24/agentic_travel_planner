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
    SpotDetail,
    TransportOption,
    parse_place_range,
)
from agentic_tour_planner.geonames.index import search_places
from agentic_tour_planner.llm.provider import LLMProvider, LLMUnavailableError
from agentic_tour_planner.pipeline.day_clustering import (
    balanced_geo_cluster,
    haversine,
    order_days_and_stops,
)
from agentic_tour_planner.pipeline.prompts import (
    DAY_REALIGN_SYSTEM_PROMPT,
    DETAILED_SYSTEM_PROMPT,
    build_day_realign_prompt,
    build_detailed_places_prompt,
    build_itinerary_prompt,
    strip_place_markdown,
)
from agentic_tour_planner.services.cost_estimator import CostEstimator
from agentic_tour_planner.services.planning_workers import PlanningInsightsBuilder
from agentic_tour_planner.tools.ai_stack_client import AiStackClient
from agentic_tour_planner.tools.weather import WeatherTool
from agentic_tour_planner.utils.logging import get_logger
from agentic_tour_planner.utils.profiler import StageTimer

logger = get_logger(__name__)


def _dedupe_key(plain: str) -> str:
    """Normalized matching key for a place name: lowercase, and trailing
    '(optional)' markers stripped so 'Enchey Monastery (optional)' matches
    the core 'Enchey Monastery'."""
    return re.sub(r"\s*\(optional\)$", "", plain.lower())


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
        # LLM usage per pipeline stage, filled during run() / run_detailed_places().
        # "used" lists stages where the LLM produced the result; "fallback" lists
        # stages where the LLM failed and a deterministic approach was used.
        self.llm_usage: dict[str, list[str]] = {"used": [], "fallback": []}

        # Use planner model for main itinerary generation
        self.planner_provider, self.planner_model = self.llm_provider.get_planner_model()
        logger.info(f"Initialized pipeline with planner model: {self.planner_provider}/{self.planner_model}")

    @property
    def context_summary(self) -> dict | None:
        return self._context_summary

    @property
    def context(self) -> RetrievedContext | None:
        return self._context

    def _record_llm_site(self, stage: str, used: bool) -> None:
        bucket = "used" if used else "fallback"
        if stage not in self.llm_usage[bucket]:
            self.llm_usage[bucket].append(stage)

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
            planner_fell_back = False
            try:
                plan_json = await self.llm_provider.complete_json(
                    prompt,
                    request,
                )
                if not plan_json:
                    logger.warning("Planner returned empty result; using fallback plan.")
                    planner_fell_back = True
                    plan_json = self._fallback_plan(request)
            except LLMUnavailableError:
                raise
            except Exception as e:
                logger.error(f"Planner failed, using fallback: {e}")
                planner_fell_back = True
                plan_json = self._fallback_plan(request)
        self._record_llm_site("itinerary planner", used=not planner_fell_back)

        # ── Phase 4: Parallel post-processing ───────────────────────────
        planner_provider, planner_model = self.llm_provider.last_planner_used()
        worker_meta = self.insights_builder.last_worker_used
        if worker_meta:
            for stage, meta in worker_meta.items():
                self._record_llm_site(
                    f"{stage} guidance",
                    used=bool(meta) and meta != ("fallback", "heuristic"),
                )
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
                # "transport" is the inverse shape: a single string. LLMs
                # sometimes emit a list — coerce it instead of failing the plan.
                transport_value = item.get("transport")
                if transport_value is None:
                    item["transport"] = ""
                elif isinstance(transport_value, list):
                    item["transport"] = " ".join(str(v) for v in transport_value)
                itinerary.append(DayPlan.model_validate(item))

            # Clean spot names: the planner sometimes wraps real names in **bold**
            # markdown (e.g. "**Nathula Pass**"). The renderer treats `name` as
            # literal text, so strip emphasis before downstream stages use it.
            for day in itinerary:
                for spot in day.spots:
                    spot.name = strip_place_markdown(spot.name)

            # --- Deterministic day clustering (soft places/day preference) ---
            try:
                all_pois: list[dict] = []
                day_bounds: list[tuple[int, int]] = []
                skipped_no_coords = 0
                for day in itinerary:
                    start = len(all_pois)
                    for spot in day.spots:
                        if spot.lat is not None and spot.lon is not None:
                            all_pois.append({"name": spot.name, "lat": spot.lat, "lon": spot.lon, "spot": spot})
                        else:
                            skipped_no_coords += 1
                    day_bounds.append((start, len(all_pois)))

                if skipped_no_coords:
                    logger.warning(
                        f"Day clustering: {skipped_no_coords} POI(s) skipped "
                        f"due to missing coordinates. "
                        f"Using {len(all_pois)} POIs with coordinates."
                    )

                target_range = parse_place_range(request.places_per_day) if request.places_per_day else None

                if all_pois and len(all_pois) >= request.trip_length_days:
                    clusters = balanced_geo_cluster(
                        all_pois,
                        num_days=request.trip_length_days,
                        target_range=target_range,
                    )
                    # Keep the LLM's narrative day order: sort clusters by the
                    # earliest original day that contributed a member.
                    orig_day = [0] * len(all_pois)
                    for day_idx, (s, end) in enumerate(day_bounds):
                        for i in range(s, end):
                            orig_day[i] = day_idx
                    idx_of = {id(p): i for i, p in enumerate(all_pois)}
                    clusters.sort(key=lambda c: min(orig_day[idx_of[id(p)]] for p in c))
                    origin = None
                    if request.origin:
                        try:
                            parts = request.origin.split(",")
                            origin = (float(parts[0]), float(parts[1]))
                        except (ValueError, IndexError):
                            pass
                    clusters = order_days_and_stops(
                        clusters,
                        origin=origin,
                    )
                    # Reassign spots to days, carrying each spot's LLM-written
                    # narrative (description, hours, image_query, ...) along.
                    for d_idx, cluster in enumerate(clusters):
                        if d_idx < len(itinerary):
                            day_spots = []
                            for poi in cluster:
                                spot = poi.get("spot") or SpotDetail(name=poi["name"])
                                spot = spot.model_copy(
                                    update={
                                        "name": poi["name"],
                                        "lat": poi["lat"],
                                        "lon": poi["lon"],
                                    }
                                )
                                day_spots.append(spot)
                            itinerary[d_idx].spots = day_spots
                    logger.debug(f"Day clustering solver reassigned {len(all_pois)} POIs into {len(itinerary)} days.")
                else:
                    logger.debug(
                        f"Day clustering skipped: {len(all_pois)} POIs, need at least {request.trip_length_days}."
                    )
            except ValueError as e:
                logger.warning(f"Day clustering infeasible, keeping LLM assignment: {e}")
            except Exception as e:
                logger.warning(f"Day clustering failed, keeping LLM assignment: {e}")

            logger.debug(f"Parsed {len(itinerary)} itinerary days.")

        # --- Realign day narrative (theme/summary/hotel) with FINAL spots ----
        # The solver may have pulled places between days and reordered stops
        # inside a day. The LLM's original theme/summary/hotel describe its own
        # (pre-solver) day composition, so regenerate them from the final
        # per-day place list. Falls back to a deterministic derivation when the
        # LLM pass fails.
        if itinerary:
            async with self.profiler.atrack("Realign Day Narrative"):
                await self._realign_day_narratives(request, itinerary)

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
            if not transport_options:
                transport_options = self._fallback_transport_options(request)

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
            raw["days"] = self._dedupe_detailed_days(raw["days"], base_response)
        detailed: DetailedPlan | None = None
        if raw and isinstance(raw, dict) and raw.get("days"):
            try:
                detailed = DetailedPlan.model_validate(raw)
            except Exception as exc:
                logger.warning(f"Detailed places JSON parse failed: {exc}")
                detailed = None
        else:
            logger.warning("Detailed places generation returned no usable 'days'.")
        self._record_llm_site("detailed places", used=detailed is not None)
        return detailed

    @staticmethod
    def _dedupe_detailed_days(raw_days: list[dict], response: Any) -> list[dict]:
        """Deterministic guard against duplicated or cross-region places.

        The detailed-places stage runs one per-day LLM call. Models sometimes
        (a) list the same place twice within a day, (b) repeat a core place that
        is already scheduled on another day (e.g. adding 'Enchey Monastery
        (optional)' to a Tsomgo Lake day when Enchey is already on the Gangtok
        day), or (c) leak markdown into the place name. This normalizes names and
        removes any place that duplicates a core place from a different day.
        """
        scheduled: dict[str, int] = {}  # normalized name -> day it is scheduled on
        for day in getattr(response, "itinerary", []):
            if isinstance(day, dict):
                day_num = int(day.get("day") or 0)
                spots = day.get("spots") or []
            else:
                day_num = int(getattr(day, "day", 0) or 0)
                spots = getattr(day, "spots", None) or []
            for s in spots:
                name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
                plain = strip_place_markdown(name or "")
                key = _dedupe_key(plain)
                if key and key not in scheduled:
                    scheduled[key] = day_num

        cleaned: list[dict] = []
        for day in raw_days:
            if not isinstance(day, dict):
                continue
            day_num = int(day.get("day") or 0)
            seen: set[str] = set()
            places: list[dict] = []
            for p in day.get("places") or []:
                if not isinstance(p, dict):
                    continue
                plain = strip_place_markdown(p.get("name") or "")
                key = _dedupe_key(plain)
                if not key:
                    continue
                # A place repeated inside one day, or already scheduled as a core
                # place on another day, is dropped (kept only on its original day).
                if key in seen or (key in scheduled and scheduled[key] != day_num):
                    continue
                seen.add(key)
                if key not in scheduled:
                    scheduled[key] = day_num  # reserve for later days
                p = dict(p)
                p["name"] = plain
                places.append(p)
            day = dict(day)
            day["places"] = places
            cleaned.append(day)
        return cleaned

    # ------------------------------------------------------------- day realignment
    async def _realign_day_narratives(self, request: PlanningRequest, itinerary: list[DayPlan]) -> None:
        """Regenerate each day's theme/summary/hotel from the FINAL place list.

        The deterministic solver may have moved places between days after the
        LLM wrote its original day narrative. This pass makes the page header,
        narrative paragraph and accommodation match the places actually shown.
        Falls back to a deterministic derivation per day when the LLM fails.
        """
        if not itinerary:
            return

        day_numbers = [d.day for d in itinerary]
        concurrency = max(1, min(4, len(day_numbers)))

        async def _one(idx: int) -> bool | None:
            day = itinerary[idx]
            day_places = [s.name for s in day.spots if s.name]
            if not day_places:
                return None
            prev_places = [s.name for s in itinerary[idx - 1].spots if s.name] if idx > 0 else []
            prompt = build_day_realign_prompt(
                request,
                day_num=day.day,
                day_places=day_places,
                prev_day_places=prev_places,
                budget_level=request.budget_level,
            )
            try:
                result = await self.llm_provider.complete_json(
                    prompt,
                    request,
                    system_prompt=DAY_REALIGN_SYSTEM_PROMPT,
                )
                if result:
                    self._apply_realign(day, result)
                    logger.debug(
                        "Day realign ok day={} theme={!r} hotel={!r}", day.day, day.theme, day.hotel_recommendation
                    )
                    return True
            except Exception as exc:
                logger.warning(f"Day realign LLM failed for day {day.day}: {exc}")
            self._fallback_day_realign(request, itinerary, idx)
            return False

        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded(idx: int) -> bool | None:
            async with semaphore:
                return await _one(idx)

        outcomes = await asyncio.gather(*(_guarded(i) for i in range(len(itinerary))))
        attempted = [o for o in outcomes if o is not None]
        used_days = [o for o in attempted if o is True]
        if used_days:
            self._record_llm_site("day realign", used=True)
        if len(used_days) != len(attempted):
            self._record_llm_site("day realign", used=False)

    @staticmethod
    def _apply_realign(day: DayPlan, result: dict[str, Any]) -> None:
        """Copy the realigned narrative fields onto the day, keeping the spots
        (and everything else) untouched. Values that parse cleanly win; anything
        malformed is ignored so we never degrade a good field."""
        if isinstance(result.get("theme"), str) and result["theme"].strip():
            day.theme = result["theme"].strip()
        if isinstance(result.get("summary"), str) and result["summary"].strip():
            day.summary = result["summary"].strip()
        if isinstance(result.get("hotel_recommendation"), str) and result["hotel_recommendation"].strip():
            day.hotel_recommendation = result["hotel_recommendation"].strip()
        if isinstance(result.get("needs_hotel_change"), bool):
            day.needs_hotel_change = result["needs_hotel_change"]

    def _fallback_day_realign(self, request: PlanningRequest, itinerary: list[DayPlan], idx: int) -> None:
        """Deterministic derivation of theme/summary/hotel from the day's spots.

        No LLM involved: the day's area anchor is its first spot (TSP-ordered),
        and a hotel change is flagged only when the day's centroid moved far
        from the previous day's centroid.
        """
        day = itinerary[idx]
        spots = [s for s in day.spots if s.name]
        if not spots:
            return
        anchor = spots[0].name
        others = ", ".join(s.name for s in spots[1:3])
        day.theme = f"{request.destination}: {anchor}" + (f" & {others}" if others else "")
        day.summary = (
            f"Day {day.day} covers {anchor}"
            + (f" and nearby highlights including {others}." if others else ".")
            + " Grouped for minimal travel time between stops."
        )
        day.hotel_recommendation = f"Stay centrally in the {anchor} area so morning and evening stops are walkable."
        day.needs_hotel_change = self._day_centroid_moved(itinerary, idx)

    @staticmethod
    def _day_centroid_moved(itinerary: list[DayPlan], idx: int, threshold_km: float = 20.0) -> bool:
        """True when this day's spot centroid is > threshold_km from the previous
        day's centroid (a hotel change is then warranted)."""
        if idx == 0:
            return False

        def _centroid(day: DayPlan) -> tuple[float, float] | None:
            lats = [s.lat for s in day.spots if s.lat is not None and s.lon is not None]
            lons = [s.lon for s in day.spots if s.lat is not None and s.lon is not None]
            if not lats:
                return None
            return sum(lats) / len(lats), sum(lons) / len(lons)

        cur = _centroid(itinerary[idx])
        prev = _centroid(itinerary[idx - 1])
        if cur is None or prev is None:
            return False
        return haversine(prev, cur) > threshold_km

    def _fallback_plan(self, request: PlanningRequest) -> dict:
        """Generate a basic plan when LLM fails.

        Tries to seed real place names + coordinates from the local geonames
        index so the deterministic day-clustering solver can still produce a
        geographically sensible itinerary; degrades to generic themes if the
        index has nothing for this destination.
        """
        logger.debug(f"Generating fallback plan for {request.destination!r} days={request.trip_length_days}")
        days = []
        interests = request.interests or ["landmarks", "food", "walks"]
        all_places = self._fallback_places(request.destination)
        for day in range(1, request.trip_length_days + 1):
            theme = interests[(day - 1) % len(interests)].title()
            # Round-robin the real places across days; the clustering solver
            # rebalances them geographically afterwards.
            day_places = all_places[(day - 1) :: request.trip_length_days] if all_places else []
            spots: list[dict] = []
            for place in day_places:
                name = place.get("name", "")
                spot: dict[str, Any] = {"name": name}
                if place.get("lat") is not None and place.get("lon") is not None:
                    spot["lat"] = place["lat"]
                    spot["lon"] = place["lon"]
                spots.append(spot)
            activity_anchor = ", ".join(p.get("name", "") for p in day_places[:2]) or f"a {theme.lower()} anchor area"
            days.append(
                {
                    "day": day,
                    "theme": f"{theme} in {request.destination}",
                    "morning": [f"Start at {activity_anchor}."],
                    "afternoon": ["Explore nearby highlights and lunch locally."],
                    "evening": ["Wrap with a scenic walk and local dinner."],
                    "meals": ["Breakfast near hotel", "Lunch in activity zone", "Dinner in lively district"],
                    "logistics": ["Use one neighborhood cluster per half day."],
                    "spots": spots,
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

    @staticmethod
    def _fallback_places(destination: str, limit: int = 12) -> list[dict]:
        """Best-effort real places for a destination from the geonames index."""
        try:
            suggestions = search_places(destination, limit=limit)
        except Exception as exc:
            logger.debug(f"Fallback places lookup failed for {destination!r}: {exc}")
            return []
        places: list[dict] = []
        seen: set[str] = set()
        dest_lower = (destination or "").strip().lower()
        for s in suggestions:
            name = getattr(s, "name", None)
            if not name:
                continue
            if abs(float(s.latitude)) < 0.01 and abs(float(s.longitude)) < 0.01:
                continue
            key = str(name).strip().lower()
            if key in seen or key == dest_lower:
                continue
            seen.add(key)
            places.append({"name": str(name), "lat": float(s.latitude), "lon": float(s.longitude)})
        return places

    def _fallback_transport_options(self, request: PlanningRequest) -> list[TransportOption]:
        """Generate realistic transport options when the LLM doesn't produce any."""
        mode = (request.transport_mode or "").lower()
        dest = request.destination or ""
        options: list[TransportOption] = []

        if mode == "car":
            options = [
                TransportOption(
                    mode="Rental Car",
                    description=f"Daily rental with insurance for flexible exploration around {dest}.",
                    fare="₹1,500-2,500/day",
                    notes="Fuel, parking, and tolls extra. Book in advance during peak season.",
                ),
                TransportOption(
                    mode="Taxi/Ride-hailing",
                    description=f"App-based taxis for point-to-point travel around {dest}.",
                    fare="₹15-25/km",
                    notes="Ola and Uber available in most cities. Surge pricing during peak hours.",
                ),
                TransportOption(
                    mode="Driving",
                    description="Self-drive with personal vehicle. Parking may be limited in city centers.",
                    fare="Fuel + parking",
                    notes="Check parking availability at each destination. Carry valid license and documents.",
                ),
            ]
        elif mode == "public":
            options = [
                TransportOption(
                    mode="Metro/Subway",
                    description=f"Fastest way to cover long distances in {dest}.",
                    fare="₹30-60 per ride",
                    notes="Buy a reloadable transit card for convenience. Avoid rush hours.",
                ),
                TransportOption(
                    mode="Local Bus",
                    description=f"Budget-friendly option connecting all major areas of {dest}.",
                    fare="₹10-30 per ride",
                    notes="Routes can be crowded. Check schedules as frequency varies.",
                ),
                TransportOption(
                    mode="Auto-rickshaw",
                    description=f"Three-wheeled shared or private transport for short distances in {dest}.",
                    fare="₹20-50 per ride",
                    notes="Negotiate fare before boarding or insist on meter use.",
                ),
                TransportOption(
                    mode="Taxi",
                    description=f"Metered or app-based taxis for comfortable travel in {dest}.",
                    fare="₹15-20/km",
                    notes="Pre-book for airport transfers. Ola and Uber widely available.",
                ),
            ]
        else:
            options = [
                TransportOption(
                    mode="Train",
                    description=f"Long-distance rail connecting major cities near {dest}.",
                    fare="₹200-800 per trip",
                    notes="Book AC classes in advance. Check seat availability on IRCTC.",
                ),
                TransportOption(
                    mode="Bus",
                    description=f"Inter-city and local bus services around {dest}.",
                    fare="₹50-300 per trip",
                    notes="State-run and private operators available. Book online for long routes.",
                ),
                TransportOption(
                    mode="Metro",
                    description=f"Urban metro rail for efficient city travel in {dest}.",
                    fare="₹30-60 per ride",
                    notes="Check if metro serves your key destinations. Buy a travel card.",
                ),
                TransportOption(
                    mode="Taxi/Ride-hailing",
                    description=f"App-based taxis for convenient door-to-door travel in {dest}.",
                    fare="₹15-25/km",
                    notes="Ola, Uber, and local providers available. Expect surge pricing during peak hours.",
                ),
                TransportOption(
                    mode="Auto-rickshaw",
                    description=f"Local three-wheeled transport for short distances in {dest}.",
                    fare="₹20-50 per ride",
                    notes="Shared autos follow fixed routes. Private autos can be hired for point-to-point.",
                ),
            ]

        return options
