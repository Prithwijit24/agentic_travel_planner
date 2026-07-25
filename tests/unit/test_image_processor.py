"""Unit tests for image post-processing pipeline."""
from __future__ import annotations

import io
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from PIL import Image

from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage
from agentic_tour_planner.images.processor import (
    passes_quality_check,
    process_image,
)


def _make_test_image(width: int = 1000, height: int = 800) -> Image.Image:
    """Create a simple test image of given dimensions."""
    return Image.new("RGB", (width, height), color=(128, 64, 32))


def test_quality_check_passes():
    img = _make_test_image(1000, 800)
    assert passes_quality_check(img) is True


def test_quality_check_rejects_small():
    img = _make_test_image(400, 300)
    assert passes_quality_check(img) is False


def test_quality_check_rejects_extreme_aspect():
    img = _make_test_image(5000, 100)  # 50:1 ratio
    assert passes_quality_check(img) is False


def test_quality_check_passes_wide():
    img = _make_test_image(1920, 1080)  # ~1.78 ratio
    assert passes_quality_check(img) is True


@pytest.mark.asyncio
async def test_process_image_rejects_low_res():
    """process_image should return None for images below min resolution."""
    candidate = ImageCandidate(
        url="https://example.com/small.jpg",
        source="wikidata",
    )
    # Mock httpx to return a small image
    small_img = _make_test_image(400, 300)
    buf = io.BytesIO()
    small_img.save(buf, format="JPEG")
    buf.seek(0)

    mock_resp = MagicMock()
    mock_resp.content = buf.getvalue()
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client):
        result = await process_image(candidate, "Eiffel Tower")

    assert result is None


@pytest.mark.asyncio
async def test_process_image_passes_quality():
    """process_image should return ProcessedImage for valid images (mocking CLIP)."""
    candidate = ImageCandidate(
        url="https://example.com/good.jpg",
        source="wikidata",
        width=1920,
        height=1080,
    )
    good_img = _make_test_image(1920, 1080)
    buf = io.BytesIO()
    good_img.save(buf, format="JPEG")
    buf.seek(0)

    mock_resp = MagicMock()
    mock_resp.content = buf.getvalue()
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Mock CLIP scoring to return high score
    mock_score = MagicMock(return_value=0.35)

    # Mock NSFW to return not NSFW (False = safe)
    mock_nsfw = MagicMock(return_value=False)

    # Mock dedup to return not duplicate
    mock_dedup = MagicMock(return_value=False)

    with (
        patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client),
        patch("agentic_tour_planner.images.processor._clip_score", mock_score),
        patch("agentic_tour_planner.images.processor._is_nsfw", mock_nsfw),
        patch("agentic_tour_planner.images.processor._is_duplicate", mock_dedup),
        patch("agentic_tour_planner.images.processor._compute_phash", return_value="abc123def456"),
        patch("agentic_tour_planner.images.processor._smart_crop", lambda img, **kw: img),
    ):
        result = await process_image(candidate, "Eiffel Tower")

    assert result is not None
    assert isinstance(result, ProcessedImage)
    assert result.clip_score == 0.35
    assert result.source == "wikidata"
    assert result.verified is True
