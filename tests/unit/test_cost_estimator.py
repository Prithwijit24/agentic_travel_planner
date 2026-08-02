"""Tests for the cost estimator, focusing on the records-based fallback.

The LLM sometimes completes all of its arithmetic through the calculator tool
and then returns an unparseable final message (prose / empty / truncated). In
that case the estimator must rebuild the estimate from the tool records instead
of handing the UI an empty "N/A" card.
"""

from agentic_tour_planner.domain.models import CostLineItem, PlanningRequest
from agentic_tour_planner.services.cost_estimator import CostEstimator


def _make_request(travelers: int = 4) -> PlanningRequest:
    return PlanningRequest(
        destination="Sikkim",
        origin="Kolkata",
        trip_length_days=4,
        interests=["nature", "monasteries"],
        budget_level="midrange",
        travel_month="September",
        transport_mode="public",
        travelers=travelers,
    )


def _calculator_records() -> list[dict]:
    return [
        {"label": "Hotel total (2 rooms x 4 nights)", "expression": "1800 * 2 * 4", "result": 14400.0, "steps": []},
        {"label": "Food total (4 people x 4 days)", "expression": "600 * 4 * 4", "result": 9600.0, "steps": []},
        {"label": "Day 1 transport (3 auto rides)", "expression": "100 * 3", "result": 300.0, "steps": []},
        {"label": "Day 1 tickets", "expression": "(100 + 100) * 4", "result": 800.0, "steps": []},
        {"label": "Day 1 total", "expression": "3600 + 2400 + 300 + 800", "result": 7100.0, "steps": []},
        {"label": "Day 2 total", "expression": "3600 + 2400 + 560 + 2800", "result": 9360.0, "steps": []},
        {"label": "Day 3 total", "expression": "3600 + 2400 + 540 + 1400", "result": 7940.0, "steps": []},
        {"label": "Day 4 total", "expression": "0 + 2400 + 1300 + 800", "result": 4500.0, "steps": []},
        {"label": "Grand total", "expression": "14400 + 9600 + 2700 + 5800", "result": 32500.0, "steps": []},
        {"label": "Per person total", "expression": "32500 / 4", "result": 8125.0, "steps": []},
    ]


def test_parse_rebuilds_estimate_from_records_when_json_unparseable():
    """A raw/error response with calculator records still yields full totals."""
    result = CostEstimator._parse({"raw": "Here is the cost breakdown:"}, _calculator_records(), _make_request())

    assert result.overall is not None
    assert result.overall.per_person_total == 8125.0
    assert result.overall.grand_total == 32500.0
    assert result.overall.members == 4

    assert [d.day for d in result.daily] == [1, 2, 3, 4]
    assert [d.subtotal for d in result.daily] == [7100.0, 9360.0, 7940.0, 4500.0]
    assert result.daily[0].items == [
        CostLineItem(label="Day 1 transport (3 auto rides)", amount=300.0),
        CostLineItem(label="Day 1 tickets", amount=800.0),
    ]


def test_parse_rebuild_derives_missing_grand_and_per_person_totals():
    """When only day totals exist, grand total and per-person are computed."""
    records = _calculator_records()[:-2]  # drop "Grand total" and "Per person total"
    result = CostEstimator._parse({"raw": "done"}, records, _make_request(travelers=2))

    assert result.overall is not None
    assert result.overall.grand_total == 7100.0 + 9360.0 + 7940.0 + 4500.0
    assert result.overall.per_person_total == round((7100.0 + 9360.0 + 7940.0 + 4500.0) / 2, 2)
    assert result.overall.members == 2


def test_parse_error_without_records_returns_empty_estimate():
    """No usable records means we fall back to the empty (calculations-only) estimate."""
    result = CostEstimator._parse({"error": "All providers failed"}, [], _make_request())

    assert result.overall is None
    assert result.daily == []


def test_parse_still_accepts_normal_json_shape():
    """The canonical shape keeps working untouched."""
    data = {
        "daily": [{"day": 1, "items": [{"label": "Hotel", "amount": "2000 rupees"}], "subtotal": "2000 rupees"}],
        "overall": {"per_person_total": "2000 rupees", "members": 1, "grand_total": "2000 rupees"},
    }
    result = CostEstimator._parse(data, [], _make_request(travelers=1))

    assert result.overall is not None
    assert result.overall.per_person_total == 2000.0
    assert result.overall.grand_total == 2000.0
    assert len(result.daily) == 1
    assert result.daily[0].items[0] == CostLineItem(label="Hotel", amount=2000.0)
