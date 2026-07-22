import pytest
from pydantic import ValidationError

from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    ImageResponse,
    LogEvent,
    PlaceImage,
    PlanAPIResponse,
    PlanningInsights,
    PlanningResponse,
    RouteGuidance,
    SpotDetail,
    TimingGuidance,
)


def _make_planning_response() -> PlanningResponse:
    return PlanningResponse(
        overview="Test plan",
        insights=PlanningInsights(
            route=RouteGuidance(strategy="direct"),
            budget=BudgetGuidance(
                estimated_daily_budget=50.0,
                estimated_total_budget=150.0,
            ),
            timing=TimingGuidance(
                season_summary="Summer",
                booking_window="2 weeks",
            ),
        ),
        provider_used="openai",
        model_used="gpt-4o",
    )


def test_planning_request_requires_destination():
    with pytest.raises(ValidationError):
        from agentic_tour_planner.domain.models import PlanningRequest

        PlanningRequest(destination="", trip_length_days=3)


def test_spot_detail_with_image_query():
    spot = SpotDetail(name="Taj Mahal", image_query="Taj Mahal sunrise")
    assert spot.image_query == "Taj Mahal sunrise"


def test_spot_detail_without_image_query():
    spot = SpotDetail(name="Taj Mahal")
    assert spot.image_query is None


def test_log_event_minimal():
    event = LogEvent(event="step", message="Planning...")
    assert event.event == "step"
    assert event.message == "Planning..."
    assert event.step is None
    assert event.detail is None
    assert event.timestamp is not None


def test_log_event_all_fields():
    event = LogEvent(
        event="debug",
        step="retrieval",
        message="Fetching sources",
        detail={"count": 5},
    )
    assert event.event == "debug"
    assert event.step == "retrieval"
    assert event.detail == {"count": 5}


def test_log_event_invalid_event_type():
    with pytest.raises(ValidationError):
        LogEvent(event="invalid", message="oops")


def test_plan_api_response_completed():
    plan = _make_planning_response()
    resp = PlanAPIResponse(
        request_id="req-123",
        plan=plan,
        status="completed",
    )
    assert resp.request_id == "req-123"
    assert resp.status == "completed"
    assert resp.error is None


def test_plan_api_response_error():
    plan = _make_planning_response()
    resp = PlanAPIResponse(
        request_id="req-456",
        plan=plan,
        status="error",
        error="Provider timeout",
    )
    assert resp.status == "error"
    assert resp.error == "Provider timeout"


def test_plan_api_response_invalid_status():
    plan = _make_planning_response()
    with pytest.raises(ValidationError):
        PlanAPIResponse(request_id="x", plan=plan, status="running")


def test_place_image_minimal():
    img = PlaceImage(place_name="Eiffel Tower", image_query="Eiffel Tower night")
    assert img.place_name == "Eiffel Tower"
    assert img.image_url is None
    assert img.source is None


def test_place_image_all_fields():
    img = PlaceImage(
        place_name="Eiffel Tower",
        image_query="Eiffel Tower night",
        image_url="https://example.com/eiffel.jpg",
        source="unsplash",
    )
    assert img.image_url == "https://example.com/eiffel.jpg"
    assert img.source == "unsplash"


def test_image_response():
    imgs = [
        PlaceImage(place_name="A", image_query="a"),
        PlaceImage(place_name="B", image_query="b", image_url="https://x.com/b.jpg"),
    ]
    resp = ImageResponse(plan_id="plan-1", images=imgs)
    assert resp.plan_id == "plan-1"
    assert len(resp.images) == 2
    assert resp.images[0].place_name == "A"


def test_image_response_empty_images():
    resp = ImageResponse(plan_id="plan-2", images=[])
    assert resp.images == []
