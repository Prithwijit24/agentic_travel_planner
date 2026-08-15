"""Pipeline orchestrator: wires sources → processor → cache."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.images.cache import (
    add_dedup_hash,
    get_cached_image,
    get_dedup_hashes,
    set_cached_image,
)
from agentic_tour_planner.images.models import ImageCandidate, ImageResult
from agentic_tour_planner.images.processor import process_image
from agentic_tour_planner.images.sources import (
    fetch_ddgs_images,
    fetch_mapillary,
    fetch_openverse,
    fetch_stack_images,
    fetch_stock,
    fetch_wikidata,
    fetch_wikimedia_commons,
    fetch_wikipedia,
)
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# Waterfall order: (fetcher, needs_coords). The fetchers have heterogeneous
# signatures (some accept lat/lng, others place_type), so the callable is typed
# as variadic to keep mypy happy while ``await``-ing each candidate list.
ImageFetcher = Callable[..., Awaitable[list[ImageCandidate]]]

_WATERFALL: list[tuple[ImageFetcher, bool]] = [
    (fetch_stack_images, False),  # #1 primary — AI Stack /images with CLIP scoring
    (fetch_ddgs_images, False),  # #2 fallback — no API key needed
    (fetch_wikidata, False),
    (fetch_wikimedia_commons, False),
    (fetch_wikipedia, False),
    (fetch_openverse, False),
    (fetch_mapillary, True),
    (fetch_stock, False),
]


def _place_id(place_name: str, lat: float | None = None, lng: float | None = None) -> str:
    """Generate a cache key from place name (and optional coordinates)."""
    slug = place_name.lower().strip().replace(" ", "-")
    if lat is not None and lng is not None:
        slug = f"{slug}:{lat:.4f},{lng:.4f}"
    return slug


async def resolve_images(places: list[dict]) -> list[ImageResult]:
    """Resolve images for a list of places.

    Each dict should have at least 'place_name' and optionally 'image_query',
    'lat', 'lng', and 'place_type'.

    Places are resolved concurrently (bounded by a semaphore) since each waterfall
    is I/O bound (network fetches), turning serial per-place latency into a single
    parallel pass.
    """
    semaphore = asyncio.Semaphore(get_settings().image_max_concurrency)

    async def _resolve_one(place: dict) -> ImageResult:
        name = place.get("place_name", "")
        query = place.get("image_query", name)
        place_type = place.get("place_type", "")
        lat = place.get("lat")
        lng = place.get("lng")
        pid = _place_id(name, lat, lng)

        # Check cache first
        cached = await get_cached_image(pid)
        if cached is not None:
            return cached

        # Run waterfall
        async with semaphore:
            return await _run_waterfall(name, query, place_type, lat, lng, pid)

    return list(await asyncio.gather(*(_resolve_one(p) for p in places)))


async def _run_waterfall(
    name: str,
    query: str,
    place_type: str,
    lat: float | None,
    lng: float | None,
    pid: str,
) -> ImageResult:
    """Try each source in order, return the first one that passes processing."""
    existing_hashes = await get_dedup_hashes(pid)
    waterfall_timeout = get_settings().image_waterfall_timeout

    for fetcher, needs_coords in _WATERFALL:
        try:
            # Guard each source with a hard timeout so a hung upstream (e.g. the
            # AI Stack /images endpoint with a 1000s client timeout) cannot stall
            # the waterfall. We only need a few good hits, not the slowest source.
            if needs_coords:
                candidates = await asyncio.wait_for(fetcher(query, lat=lat, lng=lng), timeout=waterfall_timeout)
            else:
                candidates = await asyncio.wait_for(fetcher(query), timeout=waterfall_timeout)

            if not candidates:
                continue

            # Process candidates, keep best
            best = None
            for candidate in candidates:
                processed = await process_image(candidate, name, place_type, existing_hashes)
                if processed is None:
                    continue
                if best is None or processed.clip_score > best.clip_score:
                    best = processed

            if best is not None:
                result = ImageResult(
                    place_name=name,
                    image_url=best.url,
                    source=best.source,
                    license=best.license,
                    attribution=best.attribution,
                    clip_score=best.clip_score,
                    verified=best.verified,
                    width=best.width,
                    height=best.height,
                )

                # Cache the result
                await set_cached_image(pid, result)

                # Add URL hash to dedup set
                try:
                    import hashlib

                    url_hash = hashlib.md5(best.url.encode()).hexdigest()[:16]
                    await add_dedup_hash(pid, url_hash)
                except Exception as exc:
                    logger.warning(f"Failed to record dedup hash for {name!r}: {exc}")

                logger.info(f"Resolved image for {name!r}: {best.source} (score={best.clip_score:.3f})")
                return result

        except Exception as exc:
            logger.warning(f"Source {fetcher.__name__} failed for {name!r}: {exc}")
            continue

    # All sources failed
    logger.warning(f"No image found for {name!r} from any source")
    return ImageResult(place_name=name)
