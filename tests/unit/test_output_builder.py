"""Tests for the output_builder module."""

from datetime import datetime, timezone

from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    Citation,
    CostEstimate,
    DayPlan,
    DetailedDay,
    DetailedPlan,
    PlanningInsights,
    PlanningRequest,
    PlanningResponse,
    RetrievedContext,
    RouteGuidance,
    SpotDetail,
    TimingGuidance,
    TransportOption,
)
from agentic_tour_planner.pipeline.output_builder import build_output


def _make_request() -> PlanningRequest:
    return PlanningRequest(
        destination="Kyoto",
        origin="Tokyo",
        trip_length_days=4,
        interests=["temples", "food"],
        budget_level="midrange",
        travel_month="October",
        notes="Vegetarian options preferred",
    )


def _make_context() -> RetrievedContext:
    return RetrievedContext(
        documents=[],
        search_results=[],
        place_hours=[],
        weather=None,
    )


def _make_insights() -> PlanningInsights:
    return PlanningInsights(
        route=RouteGuidance(
            strategy="Cluster temples by district",
            cluster_advice=["North Kyoto temples", "South Kyoto shrines"],
            transit_notes=["Use bus day pass"],
        ),
        budget=BudgetGuidance(
            estimated_daily_budget=100.0,
            estimated_total_budget=400.0,
            assumptions=["Mid-range dining"],
            saving_tips=["Eat at convenience stores"],
        ),
        timing=TimingGuidance(
            season_summary="Mild autumn weather",
            booking_window="2 weeks before",
            day_planning_notes=["Start early to avoid crowds"],
        ),
    )


def _make_response() -> PlanningResponse:
    return PlanningResponse(
        overview="A 4-day trip to Kyoto exploring temples and food.",
        itinerary=[
            DayPlan(
                day=1,
                theme="Temples",
                morning=["Visit Kinkaku-ji"],
                afternoon=["Explore Arashiyama"],
                evening=["Walk Gion district"],
                spots=[SpotDetail(name="Kinkaku-ji", description="Golden pavilion")],
                meals=["Breakfast at hotel", "Lunch near temple", "Dinner in Gion"],
                summary="Temple hopping day",
                transport="Bus",
                hotel_recommendation="Hotel Granvia",
            ),
        ],
        practical_tips=["Carry cash", "Wear comfortable shoes"],
        citations=[Citation(title="Kyoto Guide", url="https://example.com")],
        generated_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        provider_used="openai",
        model_used="gpt-4",
        monthly_weather="15-22°C",
        transport_options=[TransportOption(mode="Bus", fare="600 JPY", description="Day pass")],
        cost_estimate=CostEstimate(
            daily=[{"day": 1, "items": [{"label": "Food", "amount": 3000}], "subtotal": 5000}],
            overall={"members": 1, "per_person_total": 20000, "grand_total": 20000},
        ),
        worker_provider_used="openai",
        worker_model_used="gpt-4",
        live_web_brief=None,
        insights=_make_insights(),
    )


def _make_detailed() -> DetailedPlan:
    return DetailedPlan(
        days=[
            DetailedDay(
                day=1,
                theme="Temples",
                places=[
                    {
                        "name": "Kinkaku-ji",
                        "description": "Kinkaku-ji, also known as the Temple of the Golden Pavilion, is one of the most iconic temples in Kyoto. The temple was originally built in 1397 as a retirement villa for Shogun Ashikaga Yoshimitsu. The pavilion is covered in gold leaf, which creates a stunning reflection in the surrounding pond. The temple grounds include beautiful gardens and a traditional tea house. Visitors can walk around the pond and admire the architecture from different angles. The temple is particularly beautiful in autumn when the maple trees change color. The surrounding area includes several smaller temples and traditional Japanese gardens that are worth exploring. The temple receives over 2 million visitors per year, making it one of the most popular attractions in Kyoto. The entrance fee is 500 yen, and the temple is open from 9:00 AM to 5:00 PM daily. The best time to visit is early morning to avoid the crowds.",
                        "opening_closing": "9:00 AM - 5:00 PM",
                        "best_time": "Early morning",
                        "transport": "Bus 205 from Kyoto Station",
                        "key_note": "Golden pavilion temple, iconic Kyoto landmark",
                        "keywords": [],
                        "is_optional": False,
                    },
                ],
            ),
        ],
    )


def test_build_output_structure():
    """Test that build_output returns the expected structure."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    assert "request" in result
    assert "context" in result
    assert "insights" in result
    assert "response" in result
    assert "detailed" in result
    assert "profile" in result


def test_build_output_context_structure():
    """Test that context has the expected fields."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    ctx = result["context"]
    assert "documents_count" in ctx
    assert "search_results_count" in ctx
    assert "place_hours_count" in ctx
    assert "weather" in ctx


def test_build_output_insights_structure():
    """Test that insights has the expected nested structure."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    ins = result["insights"]
    assert "route" in ins
    assert "budget" in ins
    assert "timing" in ins

    assert ins["route"]["strategy"] == "Cluster temples by district"
    assert ins["budget"]["estimated_daily_budget"] == 100.0
    assert ins["timing"]["season_summary"] == "Mild autumn weather"


def test_build_output_response_structure():
    """Test that response has the expected fields."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    resp = result["response"]
    assert "plan_id" in resp
    assert "overview" in resp
    assert "monthly_weather" in resp
    assert "travel_month" in resp
    assert "transport_options" in resp
    assert "cost_estimate" in resp
    assert "itinerary" in resp
    assert "practical_tips" in resp
    assert "citations" in resp
    assert "provider_used" in resp
    assert "model_used" in resp
    assert "worker_provider_used" in resp
    assert "worker_model_used" in resp
    assert "live_web_brief" in resp
    assert "worker_routing" in resp
    assert "generated_at" in resp
    assert "metrics" in resp


def test_build_output_travel_month_from_request():
    """Test that travel_month comes from the request."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    assert result["response"]["travel_month"] == "October"


def test_build_output_with_detailed():
    """Test that detailed plan is included when provided."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()
    detailed = _make_detailed()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
        detailed=detailed,
    )

    assert result["detailed"] is not None
    assert "days" in result["detailed"]


def test_build_output_without_detailed():
    """Test that detailed is None when not provided."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    assert result["detailed"] is None


def test_build_output_profile_rows():
    """Test that profile_rows are included when provided."""
    request = _make_request()
    context = _make_context()
    insights = _make_insights()
    response = _make_response()
    profile_rows = [{"stage": "TOTAL", "elapsed_s": 10.5, "pct": 100.0}]

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
        profile_rows=profile_rows,
    )

    assert result["profile"] == profile_rows
