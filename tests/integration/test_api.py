from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agentic_tour_planner.api.main import app
from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    PlanningInsights,
    PlanningResponse,
    RouteGuidance,
    TimingGuidance,
)


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_endpoint_is_available():
    client = TestClient(app)
    response = client.get("/metrics")

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


@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@patch("agentic_tour_planner.api.main.AgenticTourPlannerPipeline")
def test_create_plan_returns_plan_api_response(mock_pipeline_cls, mock_store_cls):
    mock_pipeline = mock_pipeline_cls.return_value
    mock_store = mock_store_cls.return_value
    mock_pipeline.run = AsyncMock(return_value=_make_plan_response())

    client = TestClient(app)
    response = client.post(
        "/plans",
        json={"destination": "Paris", "trip_length_days": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert "request_id" in body
    assert "plan" in body
    assert body["plan"]["overview"] == "Test plan"
    assert body["error"] is None


@patch("agentic_tour_planner.api.main.SQLitePlanStore")
@patch("agentic_tour_planner.api.main.AgenticTourPlannerPipeline")
def test_create_plan_returns_error_status_on_failure(mock_pipeline_cls, mock_store_cls):
    mock_pipeline = mock_pipeline_cls.return_value
    mock_pipeline.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    client = TestClient(app)
    response = client.post(
        "/plans",
        json={"destination": "Paris", "trip_length_days": 3},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "request_id" in body
    assert body["plan"] is None
    assert "LLM unavailable" in body["error"]
