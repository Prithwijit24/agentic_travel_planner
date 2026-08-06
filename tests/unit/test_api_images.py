"""Tests for the rewritten api/images.py module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agentic_tour_planner.api.images import collect_places_for_images, resolve_images
from agentic_tour_planner.domain.models import (
    BudgetGuidance,
    DayPlan,
    PlaceImage,
    PlanningInsights,
    PlanningResponse,
    RouteGuidance,
    SpotDetail,
    TimingGuidance,
)
from agentic_tour_planner.images.models import ImageResult


@pytest.mark.asyncio
async def test_resolve_images_delegates_to_pipeline():
    """api.images.resolve_images should delegate to images.pipeline.resolve_images."""
    mock_results = [
        ImageResult(
            place_name="Eiffel Tower",
            image_url="https://example.com/eiffel.jpg",
            source="wikidata",
            license="CC BY-SA 4.0",
            attribution="John Doe",
            clip_score=0.42,
            verified=True,
            width=800,
            height=600,
        )
    ]

    with patch(
        "agentic_tour_planner.api.images._pipeline_resolve",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        places = [{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}]
        results = await resolve_images(places)

    assert len(results) == 1
    assert isinstance(results[0], PlaceImage)
    assert results[0].place_name == "Eiffel Tower"
    assert results[0].license == "CC BY-SA 4.0"
    assert results[0].clip_score == 0.42
    assert results[0].verified is True
    assert results[0].width == 800
    assert results[0].height == 600


@pytest.mark.asyncio
async def test_resolve_images_returns_empty_for_empty_input():
    """Empty input should return empty list."""
    results = await resolve_images([])
    assert results == []


@pytest.mark.asyncio
async def test_resolve_images_handles_none_fields():
    """Pipeline results with None fields should map correctly."""
    mock_results = [
        ImageResult(
            place_name="Unknown Place",
            image_url=None,
            source=None,
            license=None,
            attribution=None,
            clip_score=None,
            verified=False,
            width=None,
            height=None,
        )
    ]

    with patch(
        "agentic_tour_planner.api.images._pipeline_resolve",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        results = await resolve_images([{"place_name": "Unknown Place", "image_query": "unknown"}])

    assert len(results) == 1
    p = results[0]
    assert p.place_name == "Unknown Place"
    assert p.image_url is None
    assert p.verified is False


def _response_with_spots(*spots: SpotDetail) -> PlanningResponse:
    return PlanningResponse(
        plan_id="p1",
        overview="",
        insights=PlanningInsights(
            route=RouteGuidance(strategy="", cluster_advice=[], transit_notes=[]),
            budget=BudgetGuidance(
                estimated_daily_budget=0.0,
                estimated_total_budget=0.0,
                assumptions=[],
                saving_tips=[],
            ),
            timing=TimingGuidance(season_summary="", booking_window="", day_planning_notes=[]),
        ),
        provider_used="fallback",
        model_used="heuristic",
        itinerary=[DayPlan(day=1, theme="", spots=list(spots))],
        practical_tips=[],
        citations=[],
    )


class TestCollectPlacesForImages:
    def test_uses_llm_image_query_when_present(self):
        """The LLM's place-restricted image_query wins over name fallback."""
        resp = _response_with_spots(
            SpotDetail(name="Hanuman Tok", image_query="Hanuman Tok temple, Gangtok"),
            SpotDetail(name="MG Marg"),
        )
        places = collect_places_for_images(resp, destination="Sikkim")
        by_name = {p["place_name"]: p for p in places}
        assert by_name["Hanuman Tok"]["image_query"] == "Hanuman Tok temple, Gangtok, Sikkim"
        # Name fallback gets the destination appended plus a type anchor.
        assert by_name["MG Marg"]["image_query"] == "MG Marg, Sikkim market"

    def test_ambiguous_name_gets_place_type_restriction(self):
        """Without an LLM query, an ambiguous name (Hanuman Tok = monkey god)
        is anchored to its physical landmark type instead of the animal."""
        resp = _response_with_spots(SpotDetail(name="Hanuman Tok"))
        places = collect_places_for_images(resp, destination="Gangtok")
        q = places[0]["image_query"]
        assert "temple" in q
        assert places[0]["place_type"] == "temple"

    def test_place_type_hint_for_monasteries_and_lakes(self):
        resp = _response_with_spots(
            SpotDetail(name="Rumtek Monastery"),
            SpotDetail(name="Tsomgo Lake"),
            SpotDetail(name="Radhanagar Beach"),
        )
        places = collect_places_for_images(resp, destination="Sikkim")
        by_name = {p["place_name"]: p for p in places}
        # Name already carries its type; type hint only added when absent.
        assert by_name["Rumtek Monastery"]["image_query"] == "Rumtek Monastery, Sikkim"
        assert by_name["Tsomgo Lake"]["image_query"] == "Tsomgo Lake, Sikkim"
        assert by_name["Radhanagar Beach"]["image_query"] == "Radhanagar Beach, Sikkim"

    def test_duplicate_place_names_resolved_once(self):
        resp = _response_with_spots(SpotDetail(name="MG Marg"), SpotDetail(name="MG Marg"))
        places = collect_places_for_images(resp, destination="Gangtok")
        assert len(places) == 1
