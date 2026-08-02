"""End-to-end integration test for the destination image pipeline.

Tests the full waterfall → process → cache flow with mocked external APIs.
Verifies that the pipeline correctly tries multiple sources, processes
candidates, caches results, and returns the best-scoring image.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_tour_planner.images.models import ImageCandidate, ImageResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_candidate(
    url: str = "https://example.com/img.jpg",
    source: str = "wikidata",
    width: int = 1920,
    height: int = 1080,
    license: str = "CC-BY",
    attribution: str = "Test Author",
) -> ImageCandidate:
    return ImageCandidate(
        url=url,
        source=source,
        width=width,
        height=height,
        license=license,
        attribution=attribution,
    )


def _make_processed(
    url: str = "https://example.com/img.jpg",
    source: str = "wikidata",
    clip_score: float = 0.85,
    width: int = 1920,
    height: int = 1080,
    license: str = "CC-BY",
    attribution: str = "Test Author",
    verified: bool = True,
):
    mock = MagicMock()
    mock.url = url
    mock.source = source
    mock.clip_score = clip_score
    mock.width = width
    mock.height = height
    mock.license = license
    mock.attribution = attribution
    mock.verified = verified
    return mock


# ---------------------------------------------------------------------------
# Test: Full waterfall — first source succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waterfall_first_source_succeeds():
    """When the first source (Wikidata) returns a good candidate, pipeline should stop there."""
    from agentic_tour_planner.images.pipeline import resolve_images

    candidate = _make_candidate(url="https://commons.wikimedia.org/img1.jpg", source="wikidata")
    processed = _make_processed(url="https://commons.wikimedia.org/img1.jpg", source="wikidata", clip_score=0.9)

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed),
        patch("agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock, return_value=[candidate]),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock) as mock_wiki,
        patch("agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock) as mock_wiki_rest,
        patch("agentic_tour_planner.images.sources.fetch_openverse", new_callable=AsyncMock) as mock_ov,
        patch("agentic_tour_planner.images.sources.fetch_mapillary", new_callable=AsyncMock) as mock_map,
        patch("agentic_tour_planner.images.sources.fetch_stock", new_callable=AsyncMock) as mock_stock,
    ):
        places = [{"place_name": "Eiffel Tower", "image_query": "eiffel tower paris"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].place_name == "Eiffel Tower"
        assert results[0].image_url == "https://commons.wikimedia.org/img1.jpg"
        assert results[0].source == "wikidata"
        assert results[0].clip_score == 0.9

        # Subsequent sources should NOT have been called (waterfall short-circuits)
        mock_wiki.assert_not_called()
        mock_wiki_rest.assert_not_called()
        mock_ov.assert_not_called()
        mock_map.assert_not_called()
        mock_stock.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Waterfall falls through to second source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waterfall_falls_through_to_wikipedia():
    """When Wikidata returns nothing, pipeline should try Wikimedia Commons, then Wikipedia."""
    from agentic_tour_planner.images.pipeline import resolve_images

    candidate = _make_candidate(url="https://upload.wikimedia.org/img2.jpg", source="wikipedia")
    processed = _make_processed(url="https://upload.wikimedia.org/img2.jpg", source="wikipedia", clip_score=0.75)

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed),
        patch("agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock, return_value=[candidate]),
        patch("agentic_tour_planner.images.sources.fetch_openverse", new_callable=AsyncMock) as mock_ov,
        patch("agentic_tour_planner.images.sources.fetch_mapillary", new_callable=AsyncMock) as mock_map,
        patch("agentic_tour_planner.images.sources.fetch_stock", new_callable=AsyncMock) as mock_stock,
    ):
        places = [{"place_name": "Kyoto Temple", "image_query": "kyoto temple"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].image_url == "https://upload.wikimedia.org/img2.jpg"
        assert results[0].source == "wikipedia"

        # Openverse, Mapillary, Stock should NOT have been called
        mock_ov.assert_not_called()
        mock_map.assert_not_called()
        mock_stock.assert_not_called()


# ---------------------------------------------------------------------------
# Test: All sources fail — returns empty ImageResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waterfall_all_sources_fail():
    """When no source returns candidates, pipeline returns an empty ImageResult."""
    from agentic_tour_planner.images.pipeline import resolve_images

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_openverse", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_mapillary", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_stock", new_callable=AsyncMock, return_value=[]),
    ):
        places = [{"place_name": "Remote Island", "image_query": "remote island"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].place_name == "Remote Island"
        assert results[0].image_url is None


# ---------------------------------------------------------------------------
# Test: Cache hit — skips waterfall entirely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_skips_waterfall():
    """When a cached result exists, pipeline should return it without calling any source."""
    from agentic_tour_planner.images.pipeline import resolve_images

    cached = ImageResult(
        place_name="Tokyo Tower",
        image_url="https://cached.com/tokyo.jpg",
        source="cache",
        clip_score=0.95,
    )

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=cached),
        patch("agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock) as mock_wd,
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock) as mock_wc,
        patch("agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock) as mock_wr,
    ):
        places = [{"place_name": "Tokyo Tower", "image_query": "tokyo tower"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].image_url == "https://cached.com/tokyo.jpg"

        # No source should have been called
        mock_wd.assert_not_called()
        mock_wc.assert_not_called()
        mock_wr.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Processor rejects all candidates from first source, falls through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processor_rejects_falls_through():
    """When processing rejects all candidates from source 1, pipeline tries source 2."""
    from agentic_tour_planner.images.pipeline import resolve_images

    candidate_s1 = _make_candidate(url="https://bad.com/img.jpg", source="wikidata")
    candidate_s2 = _make_candidate(url="https://good.com/img.jpg", source="wikipedia")
    processed_s2 = _make_processed(url="https://good.com/img.jpg", source="wikipedia", clip_score=0.7)

    call_count = 0

    async def mock_process(candidate, name, place_type, existing_hashes):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return None  # Reject first candidate
        return processed_s2  # Accept second

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.process_image", side_effect=mock_process),
        patch(
            "agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock, return_value=[candidate_s1]
        ),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch(
            "agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock, return_value=[candidate_s2]
        ),
    ):
        places = [{"place_name": "Test Place", "image_query": "test"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].image_url == "https://good.com/img.jpg"
        assert results[0].source == "wikipedia"


# ---------------------------------------------------------------------------
# Test: Multiple places processed independently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_places_resolved_independently():
    """Each place in the list is resolved independently with its own waterfall."""
    from agentic_tour_planner.images.pipeline import resolve_images

    processed_a = _make_processed(url="https://a.com/img.jpg", source="wikidata", clip_score=0.9)
    processed_b = _make_processed(url="https://b.com/img.jpg", source="wikipedia", clip_score=0.7)
    candidate_a = _make_candidate(url="https://a.com/img.jpg", source="wikidata")
    candidate_b = _make_candidate(url="https://b.com/img.jpg", source="wikipedia")

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed_a),
        patch("agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock, return_value=[candidate_a]),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch(
            "agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock, return_value=[candidate_b]
        ),
    ):
        places = [
            {"place_name": "Place A", "image_query": "place a"},
            {"place_name": "Place B", "image_query": "place b"},
        ]
        results = await resolve_images(places)

        assert len(results) == 2
        assert results[0].place_name == "Place A"
        assert results[1].place_name == "Place B"


# ---------------------------------------------------------------------------
# Test: Source exception is caught, pipeline continues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_exception_continues_waterfall():
    """When a source raises an exception, pipeline should catch it and try the next source."""
    from agentic_tour_planner.images.pipeline import resolve_images

    candidate = _make_candidate(url="https://wiki.com/img.jpg", source="wikipedia")
    processed = _make_processed(url="https://wiki.com/img.jpg", source="wikipedia", clip_score=0.6)

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed),
        patch(
            "agentic_tour_planner.images.sources.fetch_wikidata",
            new_callable=AsyncMock,
            side_effect=Exception("API timeout"),
        ),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock, return_value=[candidate]),
    ):
        places = [{"place_name": "Resilient Place", "image_query": "resilient"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].image_url == "https://wiki.com/img.jpg"


# ---------------------------------------------------------------------------
# Test: Cache miss → waterfall → cache set → dedup hash added
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_cache_miss_to_hit_flow():
    """Verify the complete flow: cache miss → waterfall → process → cache set → dedup hash."""
    from agentic_tour_planner.images.pipeline import resolve_images

    candidate = _make_candidate(url="https://new.com/img.jpg", source="openverse")
    processed = _make_processed(url="https://new.com/img.jpg", source="openverse", clip_score=0.65)

    cache_set_calls = []
    hash_add_calls = []

    async def mock_cache_set(pid, result):
        cache_set_calls.append((pid, result))

    async def mock_hash_add(pid, h):
        hash_add_calls.append((pid, h))

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", side_effect=mock_cache_set),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", side_effect=mock_hash_add),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed),
        patch("agentic_tour_planner.images.sources.fetch_wikidata", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_wikipedia", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_openverse", new_callable=AsyncMock, return_value=[candidate]),
        patch("agentic_tour_planner.images.sources.fetch_mapillary", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.sources.fetch_stock", new_callable=AsyncMock, return_value=[]),
    ):
        places = [{"place_name": "New Place", "image_query": "new place"}]
        results = await resolve_images(places)

        assert len(results) == 1
        assert results[0].image_url == "https://new.com/img.jpg"
        assert len(cache_set_calls) == 1
        assert cache_set_calls[0][0] == "new-place"  # place_id slug


# ---------------------------------------------------------------------------
# Test: CLI pipeline wiring — images appear in build_output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_output_includes_images():
    """build_output should include images in the output dict when provided."""
    from unittest.mock import MagicMock

    from agentic_tour_planner.domain.models import PlaceImage
    from agentic_tour_planner.pipeline.output_builder import build_output

    request = MagicMock()
    request.model_dump.return_value = {"destination": "Test"}
    context = MagicMock()
    context.documents = []
    context.search_results = []
    context.place_hours = []
    context.weather = None
    insights = MagicMock()
    insights.route.strategy = "test"
    insights.route.cluster_advice = []
    insights.route.transit_notes = []
    insights.budget.estimated_daily_budget = 100
    insights.budget.estimated_total_budget = 300
    insights.budget.assumptions = []
    insights.budget.saving_tips = []
    insights.timing.season_summary = "test"
    insights.timing.booking_window = "test"
    insights.timing.day_planning_notes = []
    response = MagicMock()
    response.plan_id = "test-id"
    response.overview = "test overview"
    response.monthly_weather = None
    response.transport_options = []
    response.cost_estimate = None
    response.itinerary = []
    response.practical_tips = []
    response.citations = []
    response.provider_used = "test"
    response.model_used = "test"
    response.worker_provider_used = None
    response.worker_model_used = None
    response.live_web_brief = None
    response.generated_at = "2026-01-01"

    images = [
        PlaceImage(
            place_name="Test Place",
            image_query="test",
            image_url="https://example.com/img.jpg",
            source="wikidata",
            license="CC-BY",
            clip_score=0.85,
            verified=True,
            width=1920,
            height=1080,
        )
    ]

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
        images=images,
    )

    assert "images" in result
    assert len(result["images"]) == 1
    assert result["images"][0]["place_name"] == "Test Place"
    assert result["images"][0]["image_url"] == "https://example.com/img.jpg"
    assert result["images"][0]["clip_score"] == 0.85


@pytest.mark.asyncio
async def test_build_output_empty_images():
    """build_output should return empty images list when no images provided."""
    from unittest.mock import MagicMock

    from agentic_tour_planner.pipeline.output_builder import build_output

    request = MagicMock()
    request.model_dump.return_value = {}
    context = MagicMock()
    context.documents = []
    context.search_results = []
    context.place_hours = []
    context.weather = None
    insights = MagicMock()
    insights.route.strategy = "test"
    insights.route.cluster_advice = []
    insights.route.transit_notes = []
    insights.budget.estimated_daily_budget = 0
    insights.budget.estimated_total_budget = 0
    insights.budget.assumptions = []
    insights.budget.saving_tips = []
    insights.timing.season_summary = "test"
    insights.timing.booking_window = "test"
    insights.timing.day_planning_notes = []
    response = MagicMock()
    response.plan_id = "id"
    response.overview = "overview"
    response.monthly_weather = None
    response.transport_options = []
    response.cost_estimate = None
    response.itinerary = []
    response.practical_tips = []
    response.citations = []
    response.provider_used = "test"
    response.model_used = "test"
    response.worker_provider_used = None
    response.worker_model_used = None
    response.live_web_brief = None
    response.generated_at = "2026-01-01"

    result = build_output(
        request=request,
        context=context,
        insights=insights,
        response=response,
    )

    assert "images" in result
    assert result["images"] == []
