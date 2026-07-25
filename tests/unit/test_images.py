"""Tests for agentic_tour_planner.api.images — updated for the new multi-source pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_tour_planner.api.images import resolve_images


@pytest.mark.asyncio
async def test_resolve_images_returns_urls():
    """resolve_images should map ImageResult objects to PlaceImage objects."""
    mock_result = MagicMock()
    mock_result.place_name = "Eiffel Tower"
    mock_result.image_url = "https://example.com/eiffel.jpg"
    mock_result.source = "wikidata"
    mock_result.license = "CC-BY"
    mock_result.attribution = "Test Author"
    mock_result.clip_score = 0.9
    mock_result.verified = True
    mock_result.width = 1920
    mock_result.height = 1080

    with patch(
        "agentic_tour_planner.api.images._pipeline_resolve",
        new_callable=AsyncMock,
        return_value=[mock_result],
    ):
        places = [{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}]
        result = await resolve_images(places)

        assert len(result) == 1
        img = result[0]
        assert img.place_name == "Eiffel Tower"
        assert img.image_url == "https://example.com/eiffel.jpg"
        assert img.source == "wikidata"
        assert img.license == "CC-BY"
        assert img.attribution == "Test Author"
        assert img.clip_score == 0.9
        assert img.verified is True
        assert img.width == 1920
        assert img.height == 1080


@pytest.mark.asyncio
async def test_resolve_images_handles_failure():
    """When the pipeline returns a result with no URL, PlaceImage should have image_url=None."""
    mock_result = MagicMock()
    mock_result.place_name = "Unknown Place"
    mock_result.image_url = None
    mock_result.source = None
    mock_result.license = None
    mock_result.attribution = None
    mock_result.clip_score = None
    mock_result.verified = False
    mock_result.width = None
    mock_result.height = None

    with patch(
        "agentic_tour_planner.api.images._pipeline_resolve",
        new_callable=AsyncMock,
        return_value=[mock_result],
    ):
        places = [{"place_name": "Unknown Place", "image_query": "unknown"}]
        result = await resolve_images(places)

        assert len(result) == 1
        assert result[0].place_name == "Unknown Place"
        assert result[0].image_url is None


@pytest.mark.asyncio
async def test_resolve_images_empty_list():
    """resolve_images should return empty list for empty input."""
    result = await resolve_images([])
    assert result == []


@pytest.mark.asyncio
async def test_resolve_images_multiple_places():
    """resolve_images should handle multiple places correctly."""
    results = []
    for name in ["Place A", "Place B", "Place C"]:
        mock = MagicMock()
        mock.place_name = name
        mock.image_url = f"https://example.com/{name.lower().replace(' ', '_')}.jpg"
        mock.source = "wikipedia"
        mock.license = "CC0"
        mock.attribution = None
        mock.clip_score = 0.7
        mock.verified = False
        mock.width = 800
        mock.height = 600
        results.append(mock)

    with patch(
        "agentic_tour_planner.api.images._pipeline_resolve",
        new_callable=AsyncMock,
        return_value=results,
    ):
        places = [{"place_name": n, "image_query": n} for n in ["Place A", "Place B", "Place C"]]
        result = await resolve_images(places)

        assert len(result) == 3
        assert [r.place_name for r in result] == ["Place A", "Place B", "Place C"]
