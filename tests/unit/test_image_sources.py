"""Unit tests for image source fetchers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agentic_tour_planner.images.models import ImageCandidate
from agentic_tour_planner.images.sources import (
    _make_candidate,
    _sanitize_int,
    fetch_stock,
    fetch_wikidata,
    fetch_wikipedia,
)


@pytest.mark.asyncio
async def test_fetch_wikidata_returns_candidates():
    """Wikidata source should return ImageCandidate objects."""
    search_response = {"search": [{"id": "Q243", "label": "Eiffel Tower", "description": "wrought iron lattice tower"}]}
    entity_response = {
        "entities": {
            "Q243": {"claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Tour Eiffel Wikimedia Commons.jpg"}}}]}}
        }
    }
    imageinfo_response = {
        "query": {
            "pages": {
                "12345": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Tour_Eiffel.jpg/800px-Tour_Eiffel.jpg",
                            "width": 800,
                            "height": 1200,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "John Doe"},
                            },
                        }
                    ]
                }
            }
        }
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        side_effect=[
            MagicMock(status_code=200, json=lambda: search_response),
            MagicMock(status_code=200, json=lambda: entity_response),
            MagicMock(status_code=200, json=lambda: imageinfo_response),
        ]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikidata("Eiffel Tower")

    assert len(candidates) == 1
    c = candidates[0]
    assert isinstance(c, ImageCandidate)
    assert c.source == "wikidata"
    assert "Tour_Eiffel" in c.url
    assert c.license == "CC BY-SA 4.0"
    assert c.attribution == "John Doe"
    assert c.verified is True


@pytest.mark.asyncio
async def test_fetch_wikidata_no_results():
    """Wikidata source should return empty list when no entity found."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"search": []}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikidata("Nonexistent Place XYZ")

    assert candidates == []


@pytest.mark.asyncio
async def test_fetch_wikipedia_returns_candidates():
    """Wikipedia source should return ImageCandidate objects."""
    wiki_response = {
        "originalimage": {
            "source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Eiffel_Tower.jpg/800px-Eiffel_Tower.jpg",
            "width": 800,
            "height": 1200,
        },
        "license": {"name": "CC BY-SA 4.0"},
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: wiki_response))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikipedia("Eiffel Tower")

    assert len(candidates) == 1
    c = candidates[0]
    assert isinstance(c, ImageCandidate)
    assert c.source == "wikipedia"
    assert c.verified is True


@pytest.mark.asyncio
async def test_fetch_wikipedia_no_image():
    """Wikipedia source should return empty list when no image found."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"title": "Some article"}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikipedia("Nonexistent")

    assert candidates == []


@pytest.mark.asyncio
async def test_fetch_stock_returns_empty_without_keys():
    """Stock source should return empty when no API keys configured."""
    with patch("agentic_tour_planner.config.settings.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(unsplash_access_key=None, pexels_api_key=None)
        candidates = await fetch_stock("Paris")

    assert candidates == []


class TestSanitizeInt:
    def test_none_returns_none(self):
        assert _sanitize_int(None) is None

    def test_empty_string_returns_none(self):
        assert _sanitize_int("") is None

    def test_valid_int_returns_int(self):
        assert _sanitize_int(800) == 800

    def test_string_int_returns_int(self):
        assert _sanitize_int("800") == 800

    def test_invalid_string_returns_none(self):
        assert _sanitize_int("abc") is None

    def test_float_returns_int(self):
        assert _sanitize_int(800.0) == 800


class TestMakeCandidateSanitization:
    def test_empty_string_width_height_becomes_none(self):
        candidate = _make_candidate(
            url="https://example.com/img.jpg",
            source="test",
            width="",
            height="",
        )
        assert candidate.width is None
        assert candidate.height is None

    def test_string_int_width_height_converted(self):
        candidate = _make_candidate(
            url="https://example.com/img.jpg",
            source="test",
            width="800",
            height="600",
        )
        assert candidate.width == 800
        assert candidate.height == 600

    def test_none_width_height_stays_none(self):
        candidate = _make_candidate(
            url="https://example.com/img.jpg",
            source="test",
        )
        assert candidate.width is None
        assert candidate.height is None

    def test_int_width_height_preserved(self):
        candidate = _make_candidate(
            url="https://example.com/img.jpg",
            source="test",
            width=800,
            height=600,
        )
        assert candidate.width == 800
        assert candidate.height == 600
