"""Redis cache layer for the destination image pipeline.

Follows the existing RedisCache pattern from cache/redis_cache.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agentic_tour_planner.cache import RedisCache
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.images.models import ImageResult
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


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
        cache = RedisCache()
        data = await cache.get_json(_cache_key(place_id))
        if data is None:
            return None

        return ImageResult(
            place_name=data.get("place_name", ""),
            image_url=data.get("image_url"),
            source=data.get("source"),
            license=data.get("license"),
            attribution=data.get("attribution"),
            clip_score=data.get("clip_score"),
            verified=data.get("verified", False),
            width=data.get("width"),
            height=data.get("height"),
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
        cache = RedisCache()
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
        await cache.set_json(_cache_key(place_id), data, ttl_seconds=settings.image_cache_ttl_seconds)
    except Exception as exc:
        logger.warning(f"Cache set failed for {place_id!r}: {exc}")


async def get_dedup_hashes(place_id: str) -> list[str]:
    """Retrieve existing perceptual hashes for a place."""
    settings = get_settings()
    if not settings.redis_cache_enabled:
        return []

    try:
        cache = RedisCache()
        data = await cache.get_json(_hash_key(place_id))
        if data is None:
            return []
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning(f"Hash get failed for {place_id!r}: {exc}")
        return []


async def add_dedup_hash(place_id: str, phash: str) -> None:
    """Add a perceptual hash to the dedup set for a place."""
    settings = get_settings()
    if not settings.redis_cache_enabled:
        return

    try:
        cache = RedisCache()
        existing = await get_dedup_hashes(place_id)
        if phash not in existing:
            existing.append(phash)
            await cache.set_json(
                _hash_key(place_id),
                existing,
                ttl_seconds=settings.image_cache_ttl_seconds,
            )
    except Exception as exc:
        logger.warning(f"Hash add failed for {place_id!r}: {exc}")
