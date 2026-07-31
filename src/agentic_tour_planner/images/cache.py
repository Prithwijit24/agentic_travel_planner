"""Cache layer for the destination image pipeline.

Uses AI Infra Stack /cache endpoints instead of local Redis.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.images.models import ImageResult
from agentic_tour_planner.tools.ai_stack_client import AiStackClient
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_ai_stack: AiStackClient | None = None


def _get_ai_stack() -> AiStackClient:
    global _ai_stack
    if _ai_stack is None:
        _ai_stack = AiStackClient()
    return _ai_stack


def _cache_key(place_id: str) -> str:
    return f"img:{place_id}"


def _hash_key(place_id: str) -> str:
    return f"img:hashes:{place_id}"


async def get_cached_image(place_id: str) -> ImageResult | None:
    """Retrieve a cached image result by place_id. Returns None if disabled or miss."""
    settings = get_settings()
    if not settings.redis_cache_enabled:
        return None

    try:
        stack = _get_ai_stack()
        data = await stack.cache_get(_cache_key(place_id))
        value = data.get("value")
        if value is None:
            return None

        return ImageResult(
            place_name=value.get("place_name", ""),
            image_url=value.get("image_url"),
            source=value.get("source"),
            license=value.get("license"),
            attribution=value.get("attribution"),
            clip_score=value.get("clip_score"),
            verified=value.get("verified", False),
            width=value.get("width"),
            height=value.get("height"),
        )
    except Exception as exc:
        logger.warning(f"Cache get failed for {place_id!r}: {exc}")
        return None


async def set_cached_image(place_id: str, result: ImageResult) -> None:
    """Store an image result in the cache."""
    settings = get_settings()
    if not settings.redis_cache_enabled:
        return

    try:
        stack = _get_ai_stack()
        data = {
            "place_name": result.place_name,
            "image_url": result.image_url,
            "source": result.source,
            "license": result.license,
            "attribution": result.attribution,
            "clip_score": result.clip_score,
            "verified": result.verified,
            "width": result.width,
            "height": result.height,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await stack.cache_set(
            _cache_key(place_id),
            data,
            ttl_seconds=settings.image_cache_ttl_seconds,
        )
    except Exception as exc:
        logger.warning(f"Cache set failed for {place_id!r}: {exc}")


async def get_dedup_hashes(place_id: str) -> list[str]:
    """Retrieve existing content hashes for a place."""
    settings = get_settings()
    if not settings.redis_cache_enabled:
        return []

    try:
        stack = _get_ai_stack()
        data = await stack.cache_get(_hash_key(place_id))
        value = data.get("value")
        if value is None:
            return []
        return value if isinstance(value, list) else []
    except Exception as exc:
        logger.warning(f"Hash get failed for {place_id!r}: {exc}")
        return []


async def add_dedup_hash(place_id: str, phash: str) -> None:
    """Add a content hash to the dedup set for a place."""
    settings = get_settings()
    if not settings.redis_cache_enabled:
        return

    try:
        stack = _get_ai_stack()
        existing = await get_dedup_hashes(place_id)
        if phash not in existing:
            existing.append(phash)
            await stack.cache_set(
                _hash_key(place_id),
                existing,
                ttl_seconds=settings.image_cache_ttl_seconds,
            )
    except Exception as exc:
        logger.warning(f"Hash add failed for {place_id!r}: {exc}")
