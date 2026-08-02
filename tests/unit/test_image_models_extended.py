"""Tests for extended PlaceImage model."""

from __future__ import annotations

from agentic_tour_planner.domain.models import PlaceImage


def test_place_image_backward_compatible():
    """Old code creating PlaceImage with 4 fields should still work."""
    p = PlaceImage(
        place_name="Eiffel Tower",
        image_query="eiffel tower paris",
        image_url="https://example.com/eiffel.jpg",
        source="unsplash",
    )
    assert p.place_name == "Eiffel Tower"
    assert p.license is None
    assert p.verified is False


def test_place_image_with_new_fields():
    """New fields should be settable."""
    p = PlaceImage(
        place_name="Eiffel Tower",
        image_query="eiffel tower paris",
        image_url="https://example.com/eiffel.jpg",
        source="wikidata",
        license="CC BY-SA 4.0",
        attribution="John Doe",
        clip_score=0.42,
        verified=True,
        width=800,
        height=600,
    )
    assert p.license == "CC BY-SA 4.0"
    assert p.clip_score == 0.42
    assert p.verified is True
    assert p.width == 800
    assert p.height == 600
