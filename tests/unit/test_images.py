import pytest
from unittest.mock import patch, AsyncMock
from agentic_tour_planner.api.images import resolve_images
from agentic_tour_planner.domain.models import PlaceImage


@pytest.mark.asyncio
async def test_resolve_images_returns_urls():
    places = [
        {"place_name": "Fushimi Inari", "image_query": "fushimi inari shrine kyoto"},
        {"place_name": "Kinkaku-ji", "image_query": "golden pavilion kyoto"},
    ]

    with patch("agentic_tour_planner.api.images._fetch_unsplash", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = "https://images.unsplash.com/test.jpg"
        result = await resolve_images(places)

    assert len(result) == 2
    assert all(isinstance(img, PlaceImage) for img in result)
    assert result[0].image_url == "https://images.unsplash.com/test.jpg"
    assert result[0].source == "unsplash"


@pytest.mark.asyncio
async def test_resolve_images_handles_failure():
    places = [{"place_name": "Test", "image_query": "test query"}]

    with patch("agentic_tour_planner.api.images._fetch_unsplash", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None
        result = await resolve_images(places)

    assert len(result) == 1
    assert result[0].image_url is None
