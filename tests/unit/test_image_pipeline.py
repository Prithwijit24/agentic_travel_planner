"""Integration tests for the image pipeline orchestrator."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage, ImageResult
from agentic_tour_planner.images.pipeline import resolve_images


@pytest.mark.asyncio
async def test_resolve_images_returns_empty_for_empty_input():
    result = await resolve_images([])
    assert result == []


@pytest.mark.asyncio
async def test_resolve_images_returns_result_when_source_and_processing_succeed():
    """Pipeline should return a successful result when source + processor work."""
    candidate = ImageCandidate(
        url="https://example.com/eiffel.jpg",
        source="wikidata",
        width=1920,
        height=1080,
    )
    processed = ProcessedImage(
        url="https://example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.42,
        width=800,
        height=600,
    )

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.fetch_wikidata", new_callable=AsyncMock, return_value=[candidate]),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
    ):
        results = await resolve_images([{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}])

    assert len(results) == 1
    r = results[0]
    assert r.place_name == "Eiffel Tower"
    assert r.image_url == "https://example.com/eiffel.jpg"
    assert r.clip_score == 0.42


@pytest.mark.asyncio
async def test_resolve_images_returns_no_image_when_all_sources_fail():
    """Pipeline should return no image when all sources fail."""
    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.fetch_ddgs_images", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_wikidata", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_wikipedia", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_openverse", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_mapillary", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_stock", new_callable=AsyncMock, return_value=[]),
    ):
        results = await resolve_images([{"place_name": "Nonexistent Place", "image_query": "nonexistent"}])

    assert len(results) == 1
    assert results[0].image_url is None


@pytest.mark.asyncio
async def test_resolve_images_uses_cache_when_available():
    """Pipeline should return cached result when available."""
    cached = ImageResult(
        place_name="Eiffel Tower",
        image_url="https://cached.example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.5,
        verified=True,
    )

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=cached),
    ):
        results = await resolve_images([{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}])

    assert len(results) == 1
    assert results[0].image_url == "https://cached.example.com/eiffel.jpg"
