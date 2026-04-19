from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator

ProviderName = Literal["openai", "google", "ollama", "openrouter", "xai"]
BudgetLevel = Literal["budget", "midrange", "luxury"]
SourceKind = Literal["wikivoyage", "web", "youtube", "file", "search"]
CrawlBackend = Literal["httpx", "trafilatura", "crawl4ai"]
ProxyRoutingStrategy = Literal["direct", "round_robin", "hash"]


class PlanningRequest(BaseModel):
    destination: str = Field(min_length=2)
    origin: str | None = None
    trip_length_days: int = Field(default=3, ge=1, le=30)
    interests: list[str] = Field(default_factory=list)
    budget_level: BudgetLevel = "midrange"
    travel_month: str | None = None
    notes: str | None = None
    provider: ProviderName | None = None
    model: str | None = None
    include_live_data: bool = True
    max_attractions_per_day: int = Field(default=4, ge=1, le=8)

    @field_validator("budget_level", mode="before")
    @classmethod
    def normalize_budget_level(cls, value: str) -> str:
        if value == "mid-range":
            return "midrange"
        return value


class SourceDocument(BaseModel):
    source_id: str
    source_type: SourceKind
    title: str
    content: str
    url: HttpUrl | str | None = None
    metadata: dict = Field(default_factory=dict)


class SearchResult(BaseModel):
    title: str
    url: HttpUrl | str
    snippet: str


class PlaceHours(BaseModel):
    venue: str
    opening_hours: list[str] = Field(default_factory=list)
    status: str | None = None
    source: HttpUrl | str | None = None
    url: HttpUrl | str | None = None


class WeatherSnapshot(BaseModel):
    summary: str
    temperature_c: float | None = None
    feels_like_c: float | None = None
    humidity_percent: int | None = None
    wind_speed_kph: float | None = None


class RetrievedContext(BaseModel):
    documents: list[SourceDocument] = Field(default_factory=list)
    search_results: list[SearchResult] = Field(default_factory=list)
    place_hours: list[PlaceHours] = Field(default_factory=list)
    weather: WeatherSnapshot | None = None


class RouteGuidance(BaseModel):
    strategy: str
    cluster_advice: list[str] = Field(default_factory=list)
    transit_notes: list[str] = Field(default_factory=list)


class BudgetGuidance(BaseModel):
    estimated_daily_budget: float
    estimated_total_budget: float
    assumptions: list[str] = Field(default_factory=list)
    saving_tips: list[str] = Field(default_factory=list)


class TimingGuidance(BaseModel):
    season_summary: str
    booking_window: str
    day_planning_notes: list[str] = Field(default_factory=list)


class PlanningInsights(BaseModel):
    route: RouteGuidance
    budget: BudgetGuidance
    timing: TimingGuidance


class DayPlan(BaseModel):
    day: int
    theme: str
    morning: list[str] = Field(default_factory=list)
    afternoon: list[str] = Field(default_factory=list)
    evening: list[str] = Field(default_factory=list)
    meals: list[str] = Field(default_factory=list)
    logistics: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    title: str
    url: HttpUrl | str
    note: str | None = None


class PlanningResponse(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    overview: str
    itinerary: list[DayPlan] = Field(default_factory=list)
    practical_tips: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    insights: PlanningInsights
    provider_used: str
    model_used: str


class StoredPlanRecord(BaseModel):
    plan_id: str
    destination: str
    created_at: datetime
    provider_used: str
    model_used: str
    request: PlanningRequest
    response: PlanningResponse


class PlanFeedback(BaseModel):
    plan_id: str
    rating: int = Field(ge=1, le=5)
    comments: str | None = None


class SourceSeed(BaseModel):
    destination: str | None = None
    title: str
    url: HttpUrl | str
    source_type: SourceKind = "web"
    tags: list[str] = Field(default_factory=list)
    priority: int = 50
    refresh_days: int = 14
    crawl_backend: CrawlBackend | None = None
    metadata: dict = Field(default_factory=dict)


class SourceManifestDefaults(BaseModel):
    crawl_backend: CrawlBackend = "trafilatura"
    refresh_days: int = 14
    tags: list[str] = Field(default_factory=list)
    max_concurrency: int = 4


class SourceManifest(BaseModel):
    description: str | None = None
    defaults: SourceManifestDefaults = Field(default_factory=SourceManifestDefaults)
    seeds: list[SourceSeed] = Field(default_factory=list)


class IngestedSourceRecord(BaseModel):
    source_id: str
    source_key: str
    title: str
    url: HttpUrl | str | None = None
    destination: str | None = None
    source_type: SourceKind
    tags: list[str] = Field(default_factory=list)
    content_hash: str
    chunk_count: int = 0
    last_ingested_at: datetime = Field(default_factory=datetime.utcnow)
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)


class IngestionRunRecord(BaseModel):
    run_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    total_sources: int = 0
    indexed_sources: int = 0
    skipped_sources: int = 0
    failed_sources: int = 0
    indexed_chunks: int = 0


class RagEvaluationCase(BaseModel):
    question: str
    ground_truth: str
    reference_contexts: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class RagEvaluationReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metrics: dict = Field(default_factory=dict)
    output_path: str | None = None
