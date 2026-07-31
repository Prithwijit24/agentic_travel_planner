"""Unit tests for image cache layer (AiStackClient-based)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from agentic_tour_planner.images.models import ImageResult
from agentic_tour_planner.images.cache import (
    get_cached_image,
    set_cached_image,
    get_dedup_hashes,
    add_dedup_hash,
    _cache_key,
    _hash_key,
)


def test_cache_key_format():
    assert _cache_key("Q243") == "img:Q243"
    assert _cache_key("eiffel-tower") == "img:eiffel-tower"


def test_hash_key_format():
    assert _hash_key("Q243") == "img:hashes:Q243"


@pytest.mark.asyncio
async def test_get_cached_image_returns_none_when_disabled():
    """Cache should return None when Redis is disabled."""
    with patch("agentic_tour_planner.images.cache.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(redis_cache_enabled=False)
        result = await get_cached_image("Q243")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_image_returns_none_on_miss():
    """Cache should return None on cache miss."""
    mock_stack = AsyncMock()
    mock_stack.cache_get = AsyncMock(return_value={})

    with (
        patch("agentic_tour_planner.images.cache.get_settings") as mock_settings,
        patch("agentic_tour_planner.images.cache.get_ai_stack", return_value=mock_stack),
    ):
        mock_settings.return_value = MagicMock(redis_cache_enabled=True)
        result = await get_cached_image("Q243")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_image_returns_result_on_hit():
    """Cache should return ImageResult on cache hit."""
    cached_data = {
        "place_name": "Eiffel Tower",
        "image_url": "https://example.com/eiffel.jpg",
        "source": "wikidata",
        "license": "CC BY-SA 4.0",
        "attribution": "John Doe",
        "clip_score": 0.42,
        "verified": True,
        "width": 800,
        "height": 600,
        "timestamp": datetime.utcnow().isoformat(),
    }
    mock_stack = AsyncMock()
    mock_stack.cache_get = AsyncMock(return_value={"value": cached_data})

    with (
        patch("agentic_tour_planner.images.cache.get_settings") as mock_settings,
        patch("agentic_tour_planner.images.cache.get_ai_stack", return_value=mock_stack),
    ):
        mock_settings.return_value = MagicMock(redis_cache_enabled=True)
        result = await get_cached_image("Q243")
    assert result is not None
    assert result.place_name == "Eiffel Tower"
    assert result.image_url == "https://example.com/eiffel.jpg"


@pytest.mark.asyncio
async def test_set_cached_image_stores_result():
    """set_cached_image should store the result in cache."""
    result = ImageResult(
        place_name="Eiffel Tower",
        image_url="https://example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.42,
        verified=True,
    )
    mock_stack = AsyncMock()
    mock_stack.cache_set = AsyncMock()

    with (
        patch("agentic_tour_planner.images.cache.get_settings") as mock_settings,
        patch("agentic_tour_planner.images.cache.get_ai_stack", return_value=mock_stack),
    ):
        mock_settings.return_value = MagicMock(
            redis_cache_enabled=True, image_cache_ttl_seconds=2592000
        )
        await set_cached_image("Q243", result)
        mock_stack.cache_set.assert_called_once()


@pytest.mark.asyncio
async def test_get_dedup_hashes_returns_empty_when_disabled():
    """get_dedup_hashes should return empty list when Redis is disabled."""
    with patch("agentic_tour_planner.images.cache.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(redis_cache_enabled=False)
        result = await get_dedup_hashes("Q243")
    assert result == []


@pytest.mark.asyncio
async def test_get_dedup_hashes_returns_list():
    """get_dedup_hashes should return stored hashes."""
    mock_stack = AsyncMock()
    mock_stack.cache_get = AsyncMock(return_value={"value": ["abc123", "def456"]})

    with (
        patch("agentic_tour_planner.images.cache.get_settings") as mock_settings,
        patch("agentic_tour_planner.images.cache.get_ai_stack", return_value=mock_stack),
    ):
        mock_settings.return_value = MagicMock(redis_cache_enabled=True)
        result = await get_dedup_hashes("Q243")
    assert result == ["abc123", "def456"]


@pytest.mark.asyncio
async def test_add_dedup_hash_appends():
    """add_dedup_hash should append a new hash to the existing list."""
    mock_stack = AsyncMock()
    mock_stack.cache_get = AsyncMock(return_value={"value": ["abc123"]})
    mock_stack.cache_set = AsyncMock()

    with (
        patch("agentic_tour_planner.images.cache.get_settings") as mock_settings,
        patch("agentic_tour_planner.images.cache.get_ai_stack", return_value=mock_stack),
    ):
        mock_settings.return_value = MagicMock(
            redis_cache_enabled=True, image_cache_ttl_seconds=2592000
        )
        await add_dedup_hash("Q243", "def456")
        mock_stack.cache_set.assert_called_once_with(
            "img:hashes:Q243", ["abc123", "def456"], ttl_seconds=2592000
        )
