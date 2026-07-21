from __future__ import annotations

import re

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator

ProviderName = Literal["openai", "google", "ollama", "openrouter", "xai"]
BudgetLevel = Literal["budget", "midrange", "luxury"]
SourceKind = Literal["wikivoyage", "web", "youtube", "file", "search"]
CrawlBackend = Literal["trafilatura", "scrapling"]
ProxyRoutingStrategy = Literal["direct", "round_robin", "hash"]


class PlanningRequest(BaseModel):
    destination: str = Field(min_length=2)
    origin: str | None = None
    trip_length_days: int = Field(default=3, ge=1, le=30)
    interests: list[str] = Field(default_factory=list)
    budget_level: BudgetLevel = "midrange"
    travel_month: str | None = None
    notes: str | None = None
    provider: str | None = None
    model: str | None = None
    include_live_data: bool = True
    max_attractions_per_day: int = Field(default=4, ge=1, le=8)
    places_per_day: str | None = None
    transport_mode: str | None = None
    travelers: int = Field(default=1, ge=1)

    @field_validator("budget_level", mode="before")
    @classmethod
    def normalize_budget_level(cls, value: str) -> str:
        if value == "mid-range":
            return "midrange"
        return value


def parse_place_range(value: str | int | None, default: tuple[int, int] = (3, 5)) -> tuple[int, int]:
    """Normalize a natural place-count range like '3-5', '3 to 5', '3 – 5' into (min, max)."""
    if value is None:
        return default
    text = str(value)
    match = re.search(r"(\d+)\s*(?:-|–|—|to|and)?\s*(\d+)", text)
    if match:
        lo, hi = int(match.group(1)), int(match.group(2))
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)
    single = re.search(r"(\d+)", text)
    if single:
        n = int(single.group(1))
        return (n, n)
    return default


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


class LiveWebSource(BaseModel):
    """A single crawled + translated source used as live, on-the-fly evidence."""

    title: str
    url: str
    kind: str  # "video" | "blog"
    original_language: str | None = None
    audio_path: str | None = None  # local path to fetched audio (videos only)


class LiveWebBrief(BaseModel):
    """Structured, LLM-extracted live web intelligence — the authoritative source of
    truth for the planner, gathered on the fly (never stored in the knowledge base)."""

    path_instructions: str = ""
    fair_charges: str = ""
    transport_availability: str = ""
    place_reviews: str = ""
    daywise_guide: str = ""
    sources: list[LiveWebSource] = Field(default_factory=list)


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


class DayWeather(BaseModel):
    temperature_c: float | None = None
    temperature_night_c: float | None = None
    sunrise: str | None = None
    sunset: str | None = None
    humidity_percent: int | None = None
    rainfall_chance_percent: int | None = None


class SpotDetail(BaseModel):
    name: str
    slot: str | None = None
    history: str | None = None
    opening_hours: str | None = None
    closing_hours: str | None = None
    best_time: str | None = None
    description: str | None = None
    image_query: str | None = None  # LLM-generated search term for images


class Keyword(BaseModel):
    """An important term inside a place description, tagged with a category.

    ``text`` MUST appear verbatim in the description so the renderer can wrap it.
    ``category`` is one of: place, altitude, person, deity, other.
    """

    text: str
    category: str = "other"  # place | altitude | person | deity | other


class DetailedPlace(BaseModel):
    """A single place in the detailed, guidebook-style itinerary."""

    name: str
    description: str = ""  # ~200 words: history, locality, important things
    opening_closing: str | None = None  # REAL hours from Google Places tool
    best_time: str | None = None
    transport: str | None = None  # available transport with fare
    key_note: str | None = None  # ~200 word concise summary
    keywords: list[Keyword] = Field(default_factory=list)
    is_optional: bool = False


class DetailedDay(BaseModel):
    day: int
    theme: str
    places: list[DetailedPlace] = Field(default_factory=list)


class DetailedPlan(BaseModel):
    days: list[DetailedDay] = Field(default_factory=list)


class TransportOption(BaseModel):
    mode: str
    description: str | None = None
    fare: str | None = None
    notes: str | None = None


class DayPlan(BaseModel):
    day: int
    theme: str
    summary: str | None = None
    transport: str | None = None
    morning: list[str] = Field(default_factory=list)
    afternoon: list[str] = Field(default_factory=list)
    evening: list[str] = Field(default_factory=list)
    meals: list[str] = Field(default_factory=list)
    logistics: list[str] = Field(default_factory=list)
    weather: DayWeather | None = None
    spots: list[SpotDetail] = Field(default_factory=list)
    needs_hotel_change: bool = False
    hotel_recommendation: str | None = None


class CostLineItem(BaseModel):
    label: str
    amount: float


class DailyCost(BaseModel):
    day: int
    items: list[CostLineItem] = Field(default_factory=list)
    subtotal: float | None = None
    steps: list[str] = Field(default_factory=list)


class OverallCost(BaseModel):
    per_person_total: float | None = None
    members: int = 1
    grand_total: float | None = None
    steps: list[str] = Field(default_factory=list)


class CostEstimate(BaseModel):
    daily: list[DailyCost] = Field(default_factory=list)
    overall: OverallCost | None = None
    calculations: list[dict] = Field(default_factory=list)


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
    monthly_weather: str | None = None
    transport_options: list[TransportOption] = Field(default_factory=list)
    cost_estimate: CostEstimate | None = None
    worker_provider_used: str | None = None
    worker_model_used: str | None = None
    live_web_brief: LiveWebBrief | None = None


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


class LogEvent(BaseModel):
    """A single event in the SSE stream."""
    event: Literal["step", "debug", "metric", "error", "done"]
    step: str | None = None
    message: str
    detail: dict[str, Any] | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PlanAPIResponse(BaseModel):
    """Validated response the UI maps from."""
    request_id: str
    plan: PlanningResponse | None = None
    status: Literal["completed", "error"]
    error: str | None = None


class PlaceImage(BaseModel):
    place_name: str
    image_query: str
    image_url: str | None = None
    source: str | None = None


class ImageResponse(BaseModel):
    plan_id: str
    images: list[PlaceImage]
