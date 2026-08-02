"""Pydantic models for the destination image pipeline."""

from __future__ import annotations

from pydantic import BaseModel


class ImageCandidate(BaseModel):
    """A raw candidate image from a source, before validation."""

    url: str
    source: (
        str  # "wikidata", "wikimedia_commons", "wikipedia", "openverse", "mapillary", "unsplash", "pexels", "aistack"
    )
    license: str | None = None
    attribution: str | None = None
    width: int | None = None
    height: int | None = None
    verified: bool = True  # False for generic/stock fallback images
    clip_score: float | None = None  # Pre-computed CLIP score (e.g. from /images endpoint)


class ProcessedImage(BaseModel):
    """An image that has passed post-processing."""

    url: str
    source: str
    clip_score: float
    license: str | None = None
    attribution: str | None = None
    width: int
    height: int
    verified: bool = True


class ImageResult(BaseModel):
    """Final result for a single place."""

    place_name: str
    image_url: str | None = None
    source: str | None = None
    license: str | None = None
    attribution: str | None = None
    clip_score: float | None = None
    verified: bool = False
    width: int | None = None
    height: int | None = None
