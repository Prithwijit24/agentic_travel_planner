"""Unit tests for image post-processing pipeline (AiStackClient-based)."""
from __future__ import annotations

import io
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from PIL import Image

from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage


def _make_test_image(width: int = 1000, height: int = 800) -> Image.Image:
    """Create a simple test image of given dimensions."""
    return Image.new("RGB", (width, height), color=(128, 64, 32))


def _make_image_bytes(width: int = 1000, height: int = 800) -> bytes:
    """Create test image bytes of given dimensions."""
    img = _make_test_image(width, height)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_process_image_rejects_low_res():
    """process_image should return None for images below min resolution."""
    candidate = ImageCandidate(
        url="https://example.com/small.jpg",
        source="wikidata",
    )
    mock_resp = MagicMock()
    mock_resp.content = _make_image_bytes(400, 300)
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
    mock_resp = MagicMock()
    mock_resp.content = _make_image_bytes(1920, 1080)
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Mock CLIP scoring to return high score
    mock_clip_score = AsyncMock(return_value=0.35)

    with (
        patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client),
        patch("agentic_tour_planner.images.processor._clip_score", mock_clip_score),
    ):
        result = await process_image(candidate, "Eiffel Tower")

    assert result is not None
    assert isinstance(result, ProcessedImage)
    assert result.clip_score == 0.35
    assert result.source == "wikidata"
    assert result.verified is True


@pytest.mark.asyncio
async def test_process_image_rejects_extreme_aspect():
    """process_image should return None for extreme aspect ratios."""
    candidate = ImageCandidate(
        url="https://example.com/extreme.jpg",
        source="wikidata",
    )
    mock_resp = MagicMock()
    mock_resp.content = _make_image_bytes(5000, 100)
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client):
        result = await process_image(candidate, "Eiffel Tower")

    assert result is None


@pytest.mark.asyncio
async def test_process_image_content_hash_dedup():
    """process_image should skip duplicates based on content hash."""
    candidate = ImageCandidate(
        url="https://example.com/dup.jpg",
        source="wikidata",
    )
    mock_resp = MagicMock()
    mock_resp.content = _make_image_bytes(1920, 1080)
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    # Create a content hash that matches the image bytes
    import hashlib
    content_hash = hashlib.sha256(mock_resp.content).hexdigest()[:16]
    existing_hashes = [content_hash]

    with patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client):
        result = await process_image(candidate, "Eiffel Tower", existing_hashes=existing_hashes)

    assert result is None


@pytest.mark.asyncio
async def test_clip_score_returns_zero_on_failure():
    """_clip_score should return 0.0 when the stack call fails."""
    from agentic_tour_planner.images.processor import _clip_score

    mock_stack = AsyncMock()
    mock_stack.clip_similarity = AsyncMock(side_effect=Exception("Connection failed"))

    with patch("agentic_tour_planner.images.processor.get_ai_stack", return_value=mock_stack):
        score = await _clip_score(b"fake image bytes", "Eiffel Tower")

    assert score == 0.0


@pytest.mark.asyncio
async def test_clip_score_passes_base64():
    """_clip_score should pass base64-encoded image to the stack."""
    import base64
    from agentic_tour_planner.images.processor import _clip_score

    mock_stack = AsyncMock()
    mock_stack.clip_similarity = AsyncMock(return_value={"scores": [0.42]})

    image_bytes = b"fake image bytes"
    b64 = base64.b64encode(image_bytes).decode()

    with patch("agentic_tour_planner.images.processor.get_ai_stack", return_value=mock_stack):
        score = await _clip_score(image_bytes, "Eiffel Tower", "monument")

    assert score == 0.42
    mock_stack.clip_similarity.assert_called_once_with(
        text="Eiffel Tower monument",
        images_base64=[b64],
    )
