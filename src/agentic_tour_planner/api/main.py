from __future__ import annotations

import time
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from sse_starlette.sse import EventSourceResponse
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest

from agentic_tour_planner.api.events import EventEmitter, get_emitter, register_emitter, remove_emitter
from agentic_tour_planner.config.settings import Settings, get_settings
from agentic_tour_planner.domain.models import IngestedSourceRecord, PlanAPIResponse, PlanFeedback, PlanningRequest, PlanningResponse, StoredPlanRecord
from agentic_tour_planner.ingestion.service import IngestionService
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline
from agentic_tour_planner.storage.sqlite_store import SQLitePlanStore
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

settings: Settings = get_settings()

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


app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    logger.debug("Health check requested")
    return {"status": "ok", "env": settings.app_env}


@app.post("/plans", response_model=PlanAPIResponse)
async def create_plan(request: PlanningRequest) -> PlanAPIResponse:
    logger.info(f"POST /plans destination={request.destination} provider={request.provider or 'default'}")
    request_id = str(uuid4())
    pipeline = AgenticTourPlannerPipeline()
    store = SQLitePlanStore()
    provider = (request.provider or settings.default_llm_provider) or "unknown"
    REQUEST_COUNT.labels(endpoint="/plans", provider=provider).inc()
    start = time.perf_counter()
    try:
        response = await pipeline.run(request)
        store.save_plan(request, response)
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.info(f"POST /plans completed plan_id={response.plan_id} in {elapsed:.2f}s")
        return PlanAPIResponse(
            request_id=request_id,
            plan=response,
            status="completed",
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        REQUEST_LATENCY.labels(endpoint="/plans").observe(elapsed)
        logger.error(f"POST /plans failed in {elapsed:.2f}s: {e}")
        return PlanAPIResponse(
            request_id=request_id,
            plan=None,
            status="error",
            error=str(e),
        )


@app.get("/plans", response_model=list[StoredPlanRecord])
def list_plans(limit: int = 20) -> list[StoredPlanRecord]:
    logger.info(f"GET /plans limit={limit}")
    return SQLitePlanStore().list_plans(limit)


@app.get("/sources", response_model=list[IngestedSourceRecord])
def list_sources(limit: int = 100) -> list[IngestedSourceRecord]:
    logger.info(f"GET /sources limit={limit}")
    return IngestionService().list_sources(limit)


@app.post("/feedback")
def create_feedback(feedback: PlanFeedback) -> dict:
    logger.info(f"POST /feedback plan_id={feedback.plan_id}")
    SQLitePlanStore().save_feedback(feedback)
    return {"status": "recorded"}


@app.get("/metrics")
def metrics() -> Response:
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
        try:
            async for event in emitter.stream():
                yield {
                    "event": event.event,
                    "data": event.model_dump_json(),
                }
        finally:
            remove_emitter(request_id)

    return EventSourceResponse(event_generator())


def run() -> None:
    logger.info(f"Starting API server on 0.0.0.0:8000 (env={settings.app_env})")
    uvicorn.run("agentic_tour_planner.api.main:app", host="0.0.0.0", port=8000, reload=settings.app_env == "development")

