"""Trip state for the LangGraph critique loop."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class TripState(TypedDict):
    """State that flows through the critique loop."""

    # Input
    trip_meta: dict[str, Any]
    retrieved_pois: NotRequired[list[dict[str, Any]]]

    # After sequencing
    day_skeleton: NotRequired[list[dict[str, Any]]]

    # After cost agent
    cost_summary: NotRequired[dict[str, Any]]

    # Weather data
    weather: NotRequired[dict[str, Any]]

    # Critique loop
    critiques: NotRequired[list[str]]
    revision_count: NotRequired[int]
    known_limitations: NotRequired[list[str]]
