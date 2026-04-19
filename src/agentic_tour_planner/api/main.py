from __future__ import annotations

import time

import uvicorn
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from agentic_tour_planner.config.settings import Settings, get_settings
from agentic_tour_planner.domain.models import IngestedSourceRecord, PlanFeedback, PlanningRequest, PlanningResponse, StoredPlanRecord
from agentic_tour_planner.ingestion.service import IngestionService
from agentic_tour_planner.observability.metrics import REQUEST_COUNT, REQUEST_LATENCY, export_metrics
from agentic_tour_planner.services.planner import PlannerService
from agentic_tour_planner.storage.sqlite_store import SQLitePlanStore

settings: Settings = get_settings()
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
    return {"status": "ok", "env": settings.app_env}


@app.post("/plans", response_model=PlanningResponse)
async def create_plan(request: PlanningRequest) -> PlanningResponse:
    service = PlannerService()
    provider = request.provider or settings.default_llm_provider
    REQUEST_COUNT.labels(endpoint="/plans", provider=provider).inc()
    start = time.perf_counter()
    response = await service.create_plan(request)
    REQUEST_LATENCY.labels(endpoint="/plans").observe(time.perf_counter() - start)
    return response


@app.get("/plans", response_model=list[StoredPlanRecord])
def list_plans(limit: int = 20) -> list[StoredPlanRecord]:
    return SQLitePlanStore().list_plans(limit)


@app.get("/sources", response_model=list[IngestedSourceRecord])
def list_sources(limit: int = 100) -> list[IngestedSourceRecord]:
    return IngestionService().list_sources(limit)


@app.post("/feedback")
def create_feedback(feedback: PlanFeedback) -> dict:
    SQLitePlanStore().save_feedback(feedback)
    return {"status": "recorded"}


@app.get("/metrics")
def metrics() -> Response:
    if not settings.enable_prometheus_metrics:
        return Response(status_code=404)
    return Response(content=export_metrics(), media_type="text/plain; version=0.0.4")


def run() -> None:
    uvicorn.run("agentic_tour_planner.api.main:app", host="0.0.0.0", port=8000, reload=settings.app_env == "development")

