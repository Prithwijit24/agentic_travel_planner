"""Post-processing pipeline for candidate images.

Stages (in order):
1. Quality/resolution filtering (cheapest — runs first)
2. CLIP relevance scoring (key quality gate)
3. Perceptual-hash deduplication
4. NSFW/content moderation
5. Smart crop / aspect normalization
"""
from __future__ import annotations

import io
from typing import TYPE_CHECKING

import httpx
from PIL import Image

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage
from agentic_tour_planner.utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

# Lazy-loaded singletons for heavy ML models
_clip_model = None
_clip_processor = None
_nsfw_classifier = None


def _get_clip():
    """Lazy-load CLIP model and processor."""
    global _clip_model, _clip_processor
    if _clip_model is None:
        from transformers import CLIPModel, CLIPProcessor

        logger.info("Loading CLIP model (openai/clip-vit-base-patch32)...")
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model.eval()
    return _clip_model, _clip_processor


def _get_nsfw():
    """Lazy-load NSFW classifier."""
    global _nsfw_classifier
    if _nsfw_classifier is None:
        from transformers import pipeline as hf_pipeline

        logger.info("Loading NSFW classifier (Falconsai/nsfw_image_detection)...")
        _nsfw_classifier = hf_pipeline(
            "image-classification", model="Falconsai/nsfw_image_detection"
        )
    return _nsfw_classifier


# ── Stage 1: Quality filtering ──────────────────────────────────────


def passes_quality_check(
    image: Image.Image,
    min_dim: int | None = None,
    max_aspect_ratio: float | None = None,
) -> bool:
    """Check if image meets minimum quality requirements."""
    settings = get_settings()
    min_dim = min_dim or settings.image_min_resolution
    max_aspect_ratio = max_aspect_ratio or settings.image_max_aspect_ratio

    w, h = image.size
    if min(w, h) < min_dim:
        return False
    if max(w, h) / min(w, h) > max_aspect_ratio:
        return False
    return True


# ── Stage 2: CLIP relevance scoring ─────────────────────────────────


def _clip_score(image: Image.Image, place_name: str, place_type: str = "") -> float:
    """Compute CLIP relevance score between image and text prompt."""
    import torch

    model, processor = _get_clip()

    text = f"a photo of {place_name}, {place_type}".strip() if place_type else f"a photo of {place_name}"
    inputs = processor(text=[text], images=image, return_tensors="pt", padding=True)

    with torch.no_grad():
        outputs = model(**inputs)

    score = outputs.logits_per_image.softmax(dim=1)[0][0].item()
    return score


# ── Stage 3: Perceptual-hash deduplication ───────────────────────────


def _compute_phash(image: Image.Image) -> str:
    """Compute perceptual hash of an image, return as hex string."""
    import imagehash

    return str(imagehash.phash(image))


def _is_duplicate(new_hash: str, existing_hashes: list[str], threshold: int | None = None) -> bool:
    """Check if a hash is a near-duplicate of any existing hash."""
    import imagehash

    settings = get_settings()
    threshold = threshold or settings.image_dedup_threshold

    new_h = imagehash.hex_to_hash(new_hash)
    for h_str in existing_hashes:
        existing_h = imagehash.hex_to_hash(h_str)
        if new_h - existing_h <= threshold:
            return True
    return False


# ── Stage 4: NSFW content moderation ────────────────────────────────


def _is_nsfw(image: Image.Image) -> bool:
    """Check if image is NSFW using the Falconsai classifier."""
    settings = get_settings()
    classifier = _get_nsfw()

    result = classifier(image)
    top = max(result, key=lambda x: x["score"])
    return top["label"].lower() == "nsfw" and top["score"] > settings.image_nsfw_threshold


# ── Stage 5: Smart crop ─────────────────────────────────────────────


def _smart_crop(
    image: Image.Image, target_w: int = 800, target_h: int = 600
) -> Image.Image:
    """Crop image to target aspect ratio using center-crop fallback."""
    settings = get_settings()
    if not settings.image_smart_crop_enabled:
        return image

    try:
        import smartcrop

        sc = smartcrop.SmartCrop()
        result = sc.crop(image, width=target_w, height=target_h)
        box = result["top_crop"]
        return image.crop(
            (box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])
        )
    except ImportError:
        # Center-crop fallback
        w, h = image.size
        target_ratio = target_w / target_h
        current_ratio = w / h

        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            image = image.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            image = image.crop((0, top, w, top + new_h))

        return image.resize((target_w, target_h), Image.Resampling.LANCZOS)


# ── Main pipeline ───────────────────────────────────────────────────


async def process_image(
    candidate: ImageCandidate,
    place_name: str,
    place_type: str = "",
    existing_hashes: list[str] | None = None,
) -> ProcessedImage | None:
    """Run a candidate image through the full post-processing pipeline.

    Returns ProcessedImage if the image passes all stages, or None if rejected.
    """
    # Download image bytes
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(candidate.url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        logger.warning(f"Failed to download image {candidate.url}: {exc}")
        return None

    # Stage 1: Quality filtering (cheapest — run first)
    if not passes_quality_check(img):
        logger.debug(f"Rejected {candidate.url}: quality check failed")
        return None

    # Stage 2: CLIP relevance scoring
    score = _clip_score(img, place_name, place_type)
    settings = get_settings()
    if score < settings.image_clip_threshold:
        logger.debug(f"Rejected {candidate.url}: CLIP score {score:.3f} < {settings.image_clip_threshold}")
        return None

    # Stage 3: Deduplication
    new_hash = _compute_phash(img)
    if existing_hashes and _is_duplicate(new_hash, existing_hashes):
        logger.debug(f"Rejected {candidate.url}: duplicate detected")
        return None

    # Stage 4: NSFW check
    if _is_nsfw(img):
        logger.warning(f"Rejected {candidate.url}: NSFW content detected")
        return None

    # Stage 5: Smart crop (formatting only — never rejects)
    cropped = _smart_crop(img)

    return ProcessedImage(
        url=candidate.url,
        source=candidate.source,
        clip_score=score,
        license=candidate.license,
        attribution=candidate.attribution,
        width=cropped.size[0],
        height=cropped.size[1],
        verified=candidate.verified,
    )
