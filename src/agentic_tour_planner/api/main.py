from __future__ import annotations

import asyncio
import time
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
    ImageResponse,
    IngestedSourceRecord,
    LogEvent,
    PlanAPIResponse,
    PlanFeedback,
    PlanningRequest,
    StoredPlanRecord,
)
from agentic_tour_planner.ingestion.service import IngestionService
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
    return generate_latest()


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


@app.get("/health")
async def health() -> dict:
    logger.debug("Health check requested")
    result = {"status": "ok", "env": settings.app_env, "stack": "unknown"}
    try:
        from agentic_tour_planner.tools.ai_stack_client import AiStackClient
        stack = AiStackClient()
        stack_health = await stack.health()
        result["stack"] = "ok" if stack_health else "degraded"
    except Exception as e:
        logger.warning(f"Stack health check failed: {e}")
        result["stack"] = "unreachable"
    return result


PLAN_TIMEOUT_SECONDS = 600


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
        # Generate detailed places (rich guidebook-style descriptions) for the UI
        try:
            emitter.emit(
                LogEvent(event="step", step="Detailed Places", message="Generating detailed place descriptions...")
            )
            detailed = await pipeline.run_detailed_places(request, response, insights=response.insights)
            if detailed is not None:
                logger.info(f"Detailed places generated for plan_id={response.plan_id}")
        except Exception as det_err:
            logger.warning(f"Detailed places generation skipped (non-fatal): {det_err}")
            # Non-fatal — UI will fall back to standard spot data

        store.save_plan(request, response)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.info(f"POST /plans completed plan_id={response.plan_id} in {elapsed:.2f}s")

        # Resolve images for all spots in the itinerary
        images_result = []
        try:
            places_for_images = collect_places_for_images(response)
            if places_for_images:
                logger.info(f"Resolving images for {len(places_for_images)} places")
                images_result = await resolve_images(places_for_images)
        except Exception as img_err:
            logger.warning(f"Image resolution failed (non-fatal): {img_err}")

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
        logger.error(f"POST /plans failed in {elapsed:.2f}s: {e}")
        emitter.emit(LogEvent(event="error", message=str(e)))
        emitter.emit(
            LogEvent(
                event="done",
                message="Plan failed",
                detail={"request_id": request_id, "status": "error", "error": str(e)},
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

    places = []
    for day in record.response.itinerary:
        for spot in day.spots:
            if spot.image_query:
                places.append({"place_name": spot.name, "image_query": spot.image_query})

    images = await resolve_images(places)
    return ImageResponse(plan_id=plan_id, images=images)


@app.get("/sources", response_model=list[IngestedSourceRecord])
async def list_sources(limit: int = 100) -> list[IngestedSourceRecord]:
    logger.info(f"GET /sources limit={limit}")
    return IngestionService().list_sources(limit)


@app.post("/feedback")
async def create_feedback(feedback: PlanFeedback) -> dict:
    logger.info(f"POST /feedback plan_id={feedback.plan_id}")
    SQLitePlanStore().save_feedback(feedback)
    return {"status": "recorded"}


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
    logger.info(f"Starting API server on 0.0.0.0:8000 (env={settings.app_env})")
    uvicorn.run(
        "agentic_tour_planner.api.main:app", host="0.0.0.0", port=8000, reload=settings.app_env == "development"
    )
