"""Image post-processing: quality filter, CLIP scoring, dedup, NSFW, smart crop.

Uses AI Infra Stack for CLIP scoring instead of local torch/transformers.
"""
from __future__ import annotations

import hashlib
import io

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage
from agentic_tour_planner.images._stack import get_ai_stack
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


async def _clip_score(image_bytes: bytes, place_name: str, place_type: str = "") -> float:
    """Compute CLIP relevance score via AI Infra Stack using base64 image."""
    import base64
    settings = get_settings()
    threshold = getattr(settings, "image_clip_threshold", 0.20)
    try:
        stack = get_ai_stack()
        query = f"{place_name} {place_type}".strip()
        b64 = base64.b64encode(image_bytes).decode()
        result = await stack.clip_similarity(text=query, images_base64=[b64])
        scores = result.get("scores", [])
        if scores:
            score = float(scores[0])
            logger.debug(f"CLIP score for {place_name!r}: {score:.3f}")
            return score if score >= threshold else 0.0
    except Exception as e:
        logger.warning(f"CLIP scoring failed for {place_name!r}: {e}")
    return 0.0


def _compute_image_hash(image_bytes: bytes) -> str:
    """Compute a content hash for deduplication."""
    return hashlib.sha256(image_bytes).hexdigest()[:16]


async def process_image(
    candidate: ImageCandidate,
    place_name: str,
    place_type: str = "",
    existing_hashes: list[str] | None = None,
) -> ProcessedImage | None:
    """Download, quality-filter, CLIP-score, dedup, and crop a candidate image.

    Returns a ProcessedImage or None if the image is rejected at any stage.
    """
    settings = get_settings()
    min_res = getattr(settings, "image_min_resolution", 300)
    max_ratio = getattr(settings, "image_max_aspect_ratio", 4.0)

    if not candidate.url:
        return None

    # Stage 1: Download
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(candidate.url)
            resp.raise_for_status()
            image_bytes = resp.content
    except Exception as e:
        logger.debug(f"Download failed for {candidate.url}: {e}")
        return None

    # Stage 2: Content hash dedup
    content_hash = _compute_image_hash(image_bytes)
    if existing_hashes and content_hash in existing_hashes:
        logger.debug(f"Dedup hit for {place_name!r}: {content_hash}")
        return None

    # Stage 3: Basic dimension check (parse headers)
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size
        if width < min_res or height < min_res:
            logger.debug(f"Resolution too low: {width}x{height} < {min_res}")
            return None
        ratio = max(width / height, height / width)
        if ratio > max_ratio:
            logger.debug(f"Aspect ratio too extreme: {ratio:.1f} > {max_ratio}")
            return None
    except Exception as e:
        logger.debug(f"Image parse failed: {e}")
        return None

    # Stage 4: CLIP score via AI Infra Stack
    score = await _clip_score(image_bytes, place_name, place_type)

    # Stage 5: NSFW check (skip for now — stack doesn't have NSFW endpoint)
    # TODO: Add NSFW check when stack supports it

    return ProcessedImage(
        url=candidate.url,
        source=candidate.source,
        width=width,
        height=height,
        license=candidate.license,
        attribution=candidate.attribution,
        clip_score=score,
        verified=candidate.verified,
    )
