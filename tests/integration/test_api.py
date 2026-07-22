from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agentic_tour_planner.api.events import EventEmitter
from agentic_tour_planner.api.main import _run_plan_job, app, create_plan
from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    DayPlan,
    PlanningInsights,
    PlanningRequest,
    PlanningResponse,
    RouteGuidance,
    SpotDetail,
    StoredPlanRecord,
    TimingGuidance,
)


@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_metrics_endpoint_is_available():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "tour_planner_requests_total" in response.text


def _make_plan_response() -> PlanningResponse:
    return PlanningResponse(
        overview="Test plan",
        itinerary=[],
        practical_tips=[],
        citations=[],
        insights=PlanningInsights(
            route=RouteGuidance(strategy="direct"),
            budget=BudgetGuidance(estimated_daily_budget=100, estimated_total_budget=300),
            timing=TimingGuidance(season_summary="Spring", booking_window="2 weeks"),
        ),
        provider_used="test",
        model_used="test-model",
    )


@patch("agentic_tour_planner.api.main._run_plan_job", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_create_plan_returns_plan_api_response(mock_run_plan_job):
    response = await create_plan(PlanningRequest(destination="Paris", trip_length_days=3))

    assert response.status == "pending"
    assert response.request_id
    assert response.plan is None
    assert response.error is None


@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@patch("agentic_tour_planner.api.main._make_pipeline")
@pytest.mark.asyncio
async def test_run_plan_job_streams_error_status_on_failure(mock_make_pipeline, mock_store_cls):
    mock_pipeline = mock_make_pipeline.return_value
    mock_pipeline.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    emitter = EventEmitter()
    request = PlanningRequest(destination="Paris", trip_length_days=3)

    await _run_plan_job("req-error", request, emitter)
    events = []
    async for event in emitter.stream():
        events.append(event)

    assert events[-1].event == "done"
    assert events[-1].detail["status"] == "error"
    assert "LLM unavailable" in events[-1].detail["error"]


@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@patch("agentic_tour_planner.api.main._make_pipeline")
@pytest.mark.asyncio
async def test_run_plan_job_streams_completed_plan(mock_make_pipeline, mock_store_cls):
    mock_pipeline = mock_make_pipeline.return_value
    mock_store = mock_store_cls.return_value
    plan = _make_plan_response()
    mock_pipeline.run = AsyncMock(return_value=plan)
    emitter = EventEmitter()
    request = PlanningRequest(destination="Paris", trip_length_days=3)

    await _run_plan_job("req-ok", request, emitter)
    events = []
    async for event in emitter.stream():
        events.append(event)

    assert events[-1].event == "done"
    assert events[-1].detail["status"] == "completed"
    assert events[-1].detail["plan"]["overview"] == "Test plan"
    mock_store.save_plan.assert_called_once()


def _make_plan_with_spots() -> StoredPlanRecord:
    return StoredPlanRecord(
        plan_id="test-plan-001",
        destination="Kyoto",
        created_at="2025-01-01T00:00:00",
        provider_used="test",
        model_used="test-model",
        request={"destination": "Kyoto", "trip_length_days": 2},
        response=PlanningResponse(
            overview="Kyoto trip",
            itinerary=[
                DayPlan(
                    day=1,
                    theme="Temples",
                    spots=[
                        SpotDetail(name="Fushimi Inari", image_query="fushimi inari torii"),
                        SpotDetail(name="Kinkaku-ji", image_query="kinkaku-ji golden temple"),
                        SpotDetail(name="Tea Shop", image_query=None),
                    ],
                ),
            ],
            practical_tips=[],
            citations=[],
            insights=PlanningInsights(
                route=RouteGuidance(strategy="direct"),
                budget=BudgetGuidance(estimated_daily_budget=100, estimated_total_budget=300),
                timing=TimingGuidance(season_summary="Spring", booking_window="2 weeks"),
            ),
            provider_used="test",
            model_used="test-model",
        ),
    )


@patch("agentic_tour_planner.api.main.resolve_images", new_callable=AsyncMock)
@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@pytest.mark.asyncio
async def test_get_plan_images_returns_images(mock_store_cls, mock_resolve):
    from agentic_tour_planner.domain.models import PlaceImage

    mock_store = mock_store_cls.return_value
    mock_store.get_plan.return_value = _make_plan_with_spots()
    mock_resolve.return_value = [
        PlaceImage(
            place_name="Fushimi Inari",
            image_query="fushimi inari torii",
            image_url="http://img/1.jpg",
            source="unsplash",
        ),
        PlaceImage(
            place_name="Kinkaku-ji",
            image_query="kinkaku-ji golden temple",
            image_url="http://img/2.jpg",
            source="unsplash",
        ),
    ]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/plans/test-plan-001/images")

    assert response.status_code == 200
    body = response.json()
    assert body["plan_id"] == "test-plan-001"
    assert len(body["images"]) == 2
    assert body["images"][0]["place_name"] == "Fushimi Inari"
    assert body["images"][1]["place_name"] == "Kinkaku-ji"
    mock_resolve.assert_called_once_with(
        [
            {"place_name": "Fushimi Inari", "image_query": "fushimi inari torii"},
            {"place_name": "Kinkaku-ji", "image_query": "kinkaku-ji golden temple"},
        ]
    )


@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@pytest.mark.asyncio
async def test_get_plan_images_returns_404_when_not_found(mock_store_cls):
    mock_store = mock_store_cls.return_value
    mock_store.get_plan.return_value = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/plans/nonexistent/images")

    assert response.status_code == 404
    assert response.json()["detail"] == "Plan not found"


@patch("agentic_tour_planner.api.main.resolve_images", new_callable=AsyncMock)
@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@pytest.mark.asyncio
async def test_get_plan_images_skips_spots_without_image_query(mock_store_cls, mock_resolve):
    mock_store = mock_store_cls.return_value
    mock_store.get_plan.return_value = _make_plan_with_spots()
    mock_resolve.return_value = []

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/plans/test-plan-001/images")

    assert response.status_code == 200
    body = response.json()
    assert body["plan_id"] == "test-plan-001"
    assert body["images"] == []
    mock_resolve.assert_called_once_with(
        [
            {"place_name": "Fushimi Inari", "image_query": "fushimi inari torii"},
            {"place_name": "Kinkaku-ji", "image_query": "kinkaku-ji golden temple"},
        ]
    )
