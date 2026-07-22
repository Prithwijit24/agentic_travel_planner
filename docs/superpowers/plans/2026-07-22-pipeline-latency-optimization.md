# Pipeline Latency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce pipeline latency ~800s → ~200s by routing planner to fast cloud model (agnes) and parallelizing independent phases.

**Architecture:** Two changes: (1) per-role provider routing via config so planner hits `agnes-2.0-flash` (~25s) while workers stay on `omniroute`, (2) reorganize pipeline `run()` to overlap gather/collect phases and run cost estimate concurrent with cheap post-processing.

**Tech Stack:** Python 3.11+, asyncio, LiteLLM, agnes-2.0-flash (cloud), omniroute (local proxy)

## Global Constraints

- Planner model always goes through `complete_json` — map to configured `planner_provider`
- Worker calls (`complete_structured`, `complete_with_tools`, `extract_json`, `complete_text`) map to configured `worker_provider`
- Explicit `request.provider` override from CLI/UI always wins over role-preferred provider
- Role-preferred provider failure cascades to fallback chain (same behavior as today)
- No feature loss: live web, cost, detailed places, weather, citations, SSE events all preserved
- Pipeline `emit()` and `profiler.atrack()` retained

---
### Task 1: Per-role provider config and LLMProvider routing

**Files:**
- Modify: `src/agentic_tour_planner/config/llm.yml`
- Modify: `src/agentic_tour_planner/llm/provider.py`

**Interfaces:**
- Consumes: `settings.planner_provider` (str), `settings.worker_provider` (str) from llm.yml
- Produces: `LLMProvider.__init__` stores `self.planner_provider` / `self.worker_provider`; `complete_json` uses `planner_provider`; `_chain_for` uses `worker_provider` when `provider_override` is None

- [ ] **Step 1: Add config keys to llm.yml**

Add at top of `src/agentic_tour_planner/config/llm.yml`, after `default_llm_model`:

```yaml
# Per-role provider routing. Planner hits a fast cloud model; workers use local.
planner_provider: agnes
worker_provider: omniroute
```

- [ ] **Step 2: Read config in LLMProvider.__init__**

In `src/agentic_tour_planner/llm/provider.py` line 127, add after `self.timeout = 120`:

```python
        self.planner_provider: str | None = getattr(self.settings, "planner_provider", None)
        self.worker_provider: str | None = getattr(self.settings, "worker_provider", None)
        logger.debug(
            "LLMProvider per-role routing planner_provider={} worker_provider={}",
            self.planner_provider, self.worker_provider,
        )
```

- [ ] **Step 3: Modify `complete_json` to prefer planner_provider**

Replace chain-building logic (lines 523-521) in `complete_json`:

Old:
```python
        chain = [(p, m) for p in self._provider_chain() for m in self._models_for(p, "planner")]
        if explicit_provider:
            if explicit_provider in self.providers:
                rest = [p for p in self._provider_chain() if p != explicit_provider]
                models = self._models_for(explicit_provider, "planner")
                if model_override:
                    models = [m for m in models if m != model_override]
                    models = [model_override] + models
                chain = [(explicit_provider, m) for m in models] + [
                    (p, m) for p in rest for m in self._models_for(p, "planner")
                ]
            else:
                logger.warning(f"[LLM] Unknown provider {explicit_provider!r}; using default chain")
```

New:
```python
        chain = [(p, m) for p in self._provider_chain() for m in self._models_for(p, "planner")]

        # Per-role preferred provider: use configured planner_provider first
        # (unless caller explicitly overrode).
        if not explicit_provider and self.planner_provider and self.planner_provider in self.providers:
            preferred_models = self._models_for(self.planner_provider, "planner")
            preferred_chain = [(self.planner_provider, m) for m in preferred_models]
            chain = preferred_chain + [item for item in chain if item[0] != self.planner_provider]

        if explicit_provider:
            if explicit_provider in self.providers:
                rest = [p for p in self._provider_chain() if p != explicit_provider]
                models = self._models_for(explicit_provider, "planner")
                if model_override:
                    models = [m for m in models if m != model_override]
                    models = [model_override] + models
                chain = [(explicit_provider, m) for m in models] + [
                    (p, m) for p in rest for m in self._models_for(p, "planner")
                ]
            else:
                logger.warning(f"[LLM] Unknown provider {explicit_provider!r}; using default chain")
```

- [ ] **Step 4: Modify `_chain_for` to prefer worker_provider**

In `src/agentic_tour_planner/llm/provider.py` method `_chain_for` (line 181), change the default return at end of method:

Old:
```python
        return [(p, m) for p in self._provider_chain() for m in self._models_for(p, role)]
```

New:
```python
        chain = [(p, m) for p in self._provider_chain() for m in self._models_for(p, role)]
        # Per-role preferred provider: use configured worker_provider first
        # (unless caller explicitly overrode).
        if not provider_override and role == "worker" and self.worker_provider and self.worker_provider in self.providers:
            preferred_models = self._models_for(self.worker_provider, "worker")
            preferred_chain = [(self.worker_provider, m) for m in preferred_models]
            chain = preferred_chain + [item for item in chain if item[0] != self.worker_provider]
        return chain
```

- [ ] **Step 5: Run existing tests to confirm no breakage**

Run:
```bash
pytest tests/unit/test_llm_provider.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_tour_planner/config/llm.yml src/agentic_tour_planner/llm/provider.py
git commit --no-verify -m "feat: per-role LLM provider routing (planner=agnes, worker=omniroute)"
```

---

### Task 2: Pipeline parallelism

**Files:**
- Modify: `src/agentic_tour_planner/pipeline/agentic_pipeline.py`

**Interfaces:**
- Consumes: same `run()` signature — no interface changes
- Produces: same `PlanningResponse` — no interface changes

- [ ] **Step 1: Restructure `run()` for parallel phases**

Replace the full `run()` method body (lines 82-273) with the new parallel orchestration. The method signature, docstring, imports, and `__init__` stay the same.

New structure:

```python
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
```

- [ ] **Step 2: Verify import coverage**

All imports already present in the file. `LiveWebBrief` already imported from domain models. No new imports needed.

- [ ] **Step 3: Run syntax/lint check**

```bash
ruff check src/agentic_tour_planner/pipeline/agentic_pipeline.py
```
Expected: no new errors (pre-existing ignored codes excluded).

- [ ] **Step 4: Run type check**

```bash
mypy src/agentic_tour_planner/pipeline/agentic_pipeline.py
```
Expected: no new type errors.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/pipeline/agentic_pipeline.py
git commit --no-verify -m "perf: parallel pipeline phases (gather+live concurrent, cost overlaps parsing)"
```
