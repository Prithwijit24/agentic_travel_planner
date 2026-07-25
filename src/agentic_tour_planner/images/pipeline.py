"""Pipeline orchestrator: wires sources → processor → cache."""
from __future__ import annotations

from agentic_tour_planner.images.cache import (
    get_cached_image,
    set_cached_image,
    get_dedup_hashes,
    add_dedup_hash,
)
from agentic_tour_planner.images.models import ImageResult
from agentic_tour_planner.images.processor import process_image
from agentic_tour_planner.images.sources import (
    fetch_openverse,
    fetch_stock,
    fetch_mapillary,
    fetch_wikidata,
    fetch_wikimedia_commons,
    fetch_wikipedia,
)
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# Waterfall order: (fetcher, needs_coords)
_WATERFALL = [
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
    """
    results = []
    for place in places:
        name = place.get("place_name", "")
        query = place.get("image_query", name)
        place_type = place.get("place_type", "")
        lat = place.get("lat")
        lng = place.get("lng")
        pid = _place_id(name, lat, lng)

        # Check cache first
        cached = await get_cached_image(pid)
        if cached is not None:
            results.append(cached)
            continue

        # Run waterfall
        result = await _run_waterfall(name, query, place_type, lat, lng, pid)
        results.append(result)

    return results


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

    for fetcher, needs_coords in _WATERFALL:
        try:
            if needs_coords:
                candidates = await fetcher(query, lat=lat, lng=lng)
            else:
                candidates = await fetcher(query)

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

                # Add hash to dedup set
                try:
                    from agentic_tour_planner.images.processor import _compute_phash
                    import httpx
                    from PIL import Image
                    import io

                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.get(best.url)
                        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                        phash = _compute_phash(img)
                        await add_dedup_hash(pid, phash)
                except Exception:
                    pass  # Non-fatal

                logger.info(f"Resolved image for {name!r}: {best.source} (score={best.clip_score:.3f})")
                return result

        except Exception as exc:
            logger.warning(f"Source {fetcher.__name__} failed for {name!r}: {exc}")
            continue

    # All sources failed
    logger.warning(f"No image found for {name!r} from any source")
    return ImageResult(place_name=name)
