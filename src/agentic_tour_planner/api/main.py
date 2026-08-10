from __future__ import annotations

import asyncio
import time
from typing import cast
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest
from sse_starlette.sse import EventSourceResponse

from agentic_tour_planner.api.events import EventEmitter, get_emitter, register_emitter, remove_emitter
from agentic_tour_planner.api.images import collect_places_for_images, resolve_images
from agentic_tour_planner.config.settings import Settings, get_settings
from agentic_tour_planner.domain.models import (
    DetailedPlan,
    ImageResponse,
    LogEvent,
    PlanAPIResponse,
    PlanFeedback,
    PlanningRequest,
    StoredPlanRecord,
)
from agentic_tour_planner.pipeline.output_builder import build_output
from agentic_tour_planner.storage.sqlite_store import SQLitePlanStore
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

settings: Settings = get_settings()
_plan_tasks: set[asyncio.Task] = set()

REQUEST_COUNT = Counter(
    "tour_planner_requests_total",
    "Count of tour planner requests.",
    labelnames=("endpoint", "provider"),
)
REQUEST_LATENCY = Histogram(
    "tour_planner_request_latency_seconds",
    "Latency of tour planner requests.",
    labelnames=("endpoint",),
)


def _export_metrics() -> bytes:
    logger.debug("Exporting Prometheus metrics")
    return cast(bytes, generate_latest())


def _make_pipeline():
    from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline

    return AgenticTourPlannerPipeline()


app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


_stack_client = None


@app.get("/health")
async def health() -> dict:
    global _stack_client
    logger.debug("Health check requested")
    result = {"status": "ok", "env": settings.app_env, "stack": "unknown"}
    try:
        if _stack_client is None:
            from agentic_tour_planner.tools.ai_stack_client import AiStackClient

            _stack_client = AiStackClient()
        stack_health = await asyncio.wait_for(
            _stack_client.health(),
            timeout=5.0,
        )
        result["stack"] = "ok" if stack_health.get("status") == "healthy" else "degraded"
    except Exception as e:
        logger.warning(f"Stack health check failed: {e}")
        result["stack"] = "unreachable"
    return result


# Hard cap on a single plan job. Generous so slow LLM runs (10-15 min for a
# multi-day plan) are not killed mid-flight; the UI surfaces the failure reason.
PLAN_TIMEOUT_SECONDS = 1800


def _job_error_message(exc: Exception) -> str:
    """Human-readable failure reason for a plan job.

    ``asyncio.TimeoutError`` (the pipeline cap) has an empty ``str()``, so a raw
    pass-through would leave the UI showing a blank failure message.
    """
    if isinstance(exc, TimeoutError):
        return f"Plan generation timed out after {PLAN_TIMEOUT_SECONDS}s — the pipeline is taking too long. Please try a shorter trip or a simpler destination."
    return str(exc) or repr(exc)


@app.post("/plans", response_model=PlanAPIResponse)
async def create_plan(request: PlanningRequest) -> PlanAPIResponse:
    logger.info(f"POST /plans destination={request.destination} provider={request.provider or 'default'}")
    request_id = str(uuid4())
    emitter = EventEmitter()
    register_emitter(request_id, emitter, ttl_seconds=PLAN_TIMEOUT_SECONDS)
    task = asyncio.create_task(_run_plan_job(request_id, request, emitter))
    _plan_tasks.add(task)
    task.add_done_callback(_plan_tasks.discard)
    return PlanAPIResponse(request_id=request_id, plan=None, status="pending")


async def _run_plan_job(request_id: str, request: PlanningRequest, emitter: EventEmitter) -> None:
    store = SQLitePlanStore()
    provider = (request.provider or settings.default_llm_provider) or "unknown"
    REQUEST_COUNT.labels(endpoint="/plans", provider=provider).inc()
    start = time.perf_counter()
    try:
        pipeline = _make_pipeline()
        response = await asyncio.wait_for(
            pipeline.run(request, emitter=emitter),
            timeout=PLAN_TIMEOUT_SECONDS,
        )
        detailed = None
        images_result: list = []
        try:
            places_for_images = collect_places_for_images(response, destination=request.destination)
        except Exception as img_err:
            logger.warning(f"Image place collection failed (non-fatal): {img_err}")
            places_for_images = []

        # Detailed places (LLM, minutes) and image resolution (I/O, minutes) are
        # independent of each other — run them concurrently to cut wall-clock time.
        async def _generate_detailed() -> DetailedPlan | None:
            nonlocal detailed
            try:
                emitter.emit(
                    LogEvent(event="step", step="Detailed Places", message="Generating detailed place descriptions...")
                )
                detailed = await pipeline.run_detailed_places(request, response, insights=response.insights)
                if detailed is not None:
                    logger.info(f"Detailed places generated for plan_id={response.plan_id}")
            except Exception as det_err:
                logger.warning(f"Detailed places generation skipped (non-fatal): {det_err}")
            return detailed

        async def _resolve_images() -> list:
            import asyncio as _asyncio

            try:
                if places_for_images:
                    logger.info(f"Resolving images for {len(places_for_images)} places")
                    return await _asyncio.wait_for(resolve_images(places_for_images), timeout=180)
            except Exception as img_err:
                logger.warning(f"Image resolution failed (non-fatal): {img_err}")
            return []

        detailed_task = asyncio.create_task(_generate_detailed())
        images_task = asyncio.create_task(_resolve_images())

        # Heartbeat: emit a lightweight progress event periodically so the SSE
        # stream never sits idle long enough to hit the (600s) idle timeout while
        # the two heavy phases above run concurrently.
        async def _heartbeat() -> None:
            try:
                while True:
                    await asyncio.sleep(60)
                    emitter.emit(
                        LogEvent(
                            event="progress",
                            step="Refinements",
                            message="Still working — compiling detailed descriptions and imagery…",
                        )
                    )
            except asyncio.CancelledError:
                return

        heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            detailed = await detailed_task
            images_result = await images_task
        finally:
            heartbeat_task.cancel()

        store.save_plan(request, response)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.info(f"POST /plans completed plan_id={response.plan_id} in {elapsed:.2f}s")

        base_result = build_output(
            request=request,
            context=pipeline.context,
            insights=response.insights,
            response=response,
            detailed=detailed,
            pipeline=pipeline,
            metrics=None,
            profile_rows=pipeline.profiler.as_table(),
            images=images_result,
        )
        # Wall time + LLM usage ride along with the response payload so the UI
        # can show them on the overview page without extra plumbing.
        response_payload = base_result.setdefault("response", {})
        response_payload["wall_time_s"] = round(elapsed, 1)
        response_payload["llm_usage"] = getattr(pipeline, "llm_usage", {"used": [], "fallback": []})
        full_result = {
            "plan_id": response.plan_id,
            "request_id": request_id,
            "status": "completed",
            **base_result,
        }
        emitter.emit(LogEvent(event="done", message="Plan complete", detail=full_result))
    except Exception as e:
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        error_msg = _job_error_message(e)
        logger.error(f"POST /plans failed in {elapsed:.2f}s: {error_msg}")
        emitter.emit(LogEvent(event="error", message=error_msg))
        emitter.emit(
            LogEvent(
                event="done",
                message="Plan failed",
                detail={"request_id": request_id, "status": "error", "error": error_msg},
            )
        )
    finally:
        remove_emitter(request_id)


@app.get("/plans", response_model=list[StoredPlanRecord])
async def list_plans(limit: int = 20) -> list[StoredPlanRecord]:
    logger.info(f"GET /plans limit={limit}")
    return SQLitePlanStore().list_plans(limit)


@app.get("/plans/{plan_id}/images", response_model=ImageResponse)
async def get_plan_images(plan_id: str) -> ImageResponse:
    logger.info(f"GET /plans/{plan_id}/images")
    store = SQLitePlanStore()
    record = store.get_plan(plan_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    places = collect_places_for_images(record.response, destination=record.destination)
    images = await resolve_images(places)
    return ImageResponse(plan_id=plan_id, images=images)


@app.post("/feedback")
async def create_feedback(feedback: PlanFeedback) -> dict:
    logger.info(f"POST /feedback plan_id={feedback.plan_id}")
    SQLitePlanStore().save_feedback(feedback)
    return {"status": "recorded"}



@app.get("/destinations/{name}/interests")
async def get_destination_interests(name: str):
    """Get dynamic interest tags for a destination."""
    from agentic_tour_planner.retrieval.pipeline import get_available_tags
    tags = get_available_tags(name)
    return {"tags": tags}


@app.get("/metrics")
async def metrics() -> Response:
    logger.debug("GET /metrics")
    if not settings.enable_prometheus_metrics:
        logger.debug("Prometheus metrics disabled, returning 404")
        return Response(status_code=404)
    return Response(content=_export_metrics(), media_type="text/plain; version=0.0.4")


@app.get("/plans/stream/{request_id}")
async def stream_plan(request_id: str):
    logger.info(f"GET /plans/stream/{request_id}")
    emitter = get_emitter(request_id)
    if emitter is None:
        raise HTTPException(status_code=404, detail="Stream not found")

    async def event_generator():
        async for event in emitter.stream():
            yield {
                "event": event.event,
                "data": event.model_dump_json(),
            }

    return EventSourceResponse(event_generator())


def run() -> None:
    api_host = getattr(settings, "api_host", "127.0.0.1")
    logger.info(f"Starting API server on {api_host}:8000 (env={settings.app_env})")
    uvicorn.run("agentic_tour_planner.api.main:app", host=api_host, port=8000, reload=settings.app_env == "development")
