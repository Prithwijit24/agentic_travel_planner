"""Destination image pipeline — free, multi-source image fetching with validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_tour_planner.tools.ai_stack_client import AiStackClient

from agentic_tour_planner.images.models import ImageCandidate, ImageResult, ProcessedImage
from agentic_tour_planner.images.pipeline import resolve_images

_ai_stack: AiStackClient | None = None


def get_ai_stack() -> "AiStackClient":
    """Shared AiStackClient singleton for the images module."""
    global _ai_stack
    if _ai_stack is None:
        from agentic_tour_planner.tools.ai_stack_client import AiStackClient
        _ai_stack = AiStackClient()
    return _ai_stack


__all__ = [
    "ImageCandidate",
    "ImageResult",
    "ProcessedImage",
    "get_ai_stack",
    "resolve_images",
]
