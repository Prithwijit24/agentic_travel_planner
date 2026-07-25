"""Unit tests for image pipeline models."""

from __future__ import annotations

from agentic_tour_planner.images.models import ImageCandidate, ImageResult, ProcessedImage


def test_image_candidate_minimal():
    c = ImageCandidate(url="https://example.com/img.jpg", source="wikidata")
    assert c.url == "https://example.com/img.jpg"
    assert c.source == "wikidata"
    assert c.license is None
    assert c.attribution is None
    assert c.width is None
    assert c.height is None
    assert c.verified is True


def test_image_candidate_full():
    c = ImageCandidate(
        url="https://example.com/img.jpg",
        source="openverse",
        license="CC-BY",
        attribution="Photo by Alice",
        width=1920,
        height=1080,
        verified=False,
    )
    assert c.license == "CC-BY"
    assert c.verified is False


def test_processed_image():
    p = ProcessedImage(
        url="https://example.com/img.jpg",
        source="wikidata",
        clip_score=0.35,
        width=800,
        height=600,
    )
    assert p.clip_score == 0.35
    assert p.verified is True


def test_image_result_no_image():
    r = ImageResult(place_name="Tokyo Tower")
    assert r.image_url is None
    assert r.verified is False


def test_image_result_with_image():
    r = ImageResult(
        place_name="Eiffel Tower",
        image_url="https://example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.42,
        verified=True,
    )
    assert r.image_url == "https://example.com/eiffel.jpg"
    assert r.verified is True
