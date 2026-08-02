"""Tests for the rewritten api/images.py module."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agentic_tour_planner.api.images import resolve_images
from agentic_tour_planner.domain.models import PlaceImage
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
