# Destination Image Pipeline — Design Spec

**Date:** 2026-07-25
**Author:** Buffy (AI agent)
**Status:** Draft — awaiting user review

---

## 1. Problem Statement

The current image system (`api/images.py`) only works with Unsplash/Pexels (paid API keys), has no relevance validation, no caching, and no dedup. Images can be mismatched, low-quality, or missing entirely. There is no fallback chain.

**Goal:** Replace with a free, multi-source pipeline that fetches accurate, high-quality photos for any destination using only free, keyless-or-generous-free-tier sources, validated by an automated relevance/quality post-processing pipeline.

**Cost:** $0 for APIs. Optional self-hosted compute (CPU sufficient) for CLIP relevance checking.

---

## 2. Architecture Overview

```
Destination Name/Coordinates
        │
        ▼
┌─────────────────────────────────────────┐
│ STAGE 1: Source Waterfall (try in order) │
│  1. Wikidata (P18 image)                 │
│  2. Wikimedia Commons (category search)  │
│  3. Wikipedia REST API (lead image)      │
│  4. Openverse (CC aggregator)            │
│  5. Mapillary (street-level, optional)   │
│  6. Unsplash/Pexels (generic mood photo) │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│ STAGE 2: Post-Processing Pipeline        │
│  1. Quality/resolution filtering         │
│  2. CLIP relevance scoring               │
│  3. Perceptual-hash deduplication        │
│  4. NSFW/content moderation              │
│  5. Smart crop / aspect normalization    │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│ STAGE 3: Cache & Serve (Redis)           │
│  Store final URL + metadata per place_id │
└─────────────────────────────────────────┘
```

---

## 3. Module Structure

New package: `src/agentic_tour_planner/images/`

```
images/
├── __init__.py           # Public API: resolve_images()
├── models.py             # Pydantic models: ImageCandidate, ProcessedImage, ImageResult
├── sources.py            # Source waterfall: 6 async source functions
├── processor.py          # Post-processing pipeline: CLIP, quality, dedup, NSFW, crop
├── cache.py              # Redis cache layer (wraps existing RedisCache)
└── pipeline.py           # Orchestrator: wires sources → processor → cache
```

---

## 4. Integration Points

| File | Change | Description |
|------|--------|-------------|
| `api/images.py` | **Rewrite** | Replace Unsplash/Pexels calls with `images.pipeline.resolve_images()` |
| `domain/models.py` | **Extend** | Add fields to `PlaceImage`: `license`, `attribution`, `clip_score`, `verified`, `width`, `height` |
| `config/settings.py` | **Extend** | Add image-related settings (thresholds, TTLs, feature flags) |
| `api/main.py` | **No change** | Endpoint `GET /plans/{plan_id}/images` already calls `resolve_images` |
| `app/streamlit_app.py` | **No change** | Already fetches from the API endpoint |

---

## 5. Source Waterfall (Stage 1)

Query sources in order. Stop as soon as one returns an image that passes Stage 2. If a source returns multiple candidates, pass all through Stage 2 and keep the best-scoring one.

### 5.1 Wikidata (Primary Source)

Every notable place has a Wikidata entity with a `P18` (image) property pointing to a verified Commons file.

**Steps:**
1. Resolve destination name to Wikidata Q-ID via search API
2. Fetch entity's P18 image claim from `Special:EntityData/{QID}.json`
3. Convert filename to direct URL via Commons imageinfo API
4. Return `ImageCandidate` with URL, license, attribution metadata

**API endpoints:**
- `GET https://www.wikidata.org/w/api.php?action=wbsearchentities&search={name}&language=en&format=json&type=item`
- `GET https://www.wikidata.org/wiki/Special:EntityData/{QID}.json`
- `GET https://commons.wikimedia.org/w/api.php?action=query&titles=File:{filename}&prop=imageinfo&iiprop=url|size|extmetadata&format=json`

### 5.2 Wikimedia Commons Category Search (Fallback #1)

If P18 is missing or you want multiple candidates:

- `GET https://commons.wikimedia.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:{name}&cmtype=file&cmlimit=20&format=json`

### 5.3 Wikipedia REST API — Lead Image (Fallback #2)

Simple and fast — grabs the "hero" image from the place's Wikipedia article summary:

- `GET https://en.wikipedia.org/api/rest_v1/page/summary/{PAGE_TITLE}`
- Use `originalimage.source` (full-res) or `thumbnail.source` (small)

### 5.4 Openverse (Fallback #3)

Aggregates CC-licensed images from Flickr, museums, and other sources:

- `GET https://api.openverse.org/v1/images/?q={name}&license_type=commercial&mature=false`
- Filter to `license` in `["cc0","pdm","by","by-sa"]`
- Always keep `attribution` field

### 5.5 Mapillary (Optional Fallback #4 — Street-Level)

Useful for neighborhoods, streets, or smaller POIs:

- `GET https://graph.mapillary.com/images?fields=id,thumb_2048_url&closeto={lng},{lat}&radius=250&access_token={FREE_TOKEN}`

### 5.6 Unsplash / Pexels — Generic Mood Fallback (Last Resort)

Only when **no place-specific image** survives Stage 2. Tag these images as `"generic"` (not `"verified"`). Query by category derived from place type.

---

## 6. Post-Processing Pipeline (Stage 2)

Run every candidate image through this pipeline sequentially. Each stage can reject an image.

### 6.1 Quality & Resolution Filtering (runs first — cheapest)

- Reject if shortest side < 800px
- Reject if aspect ratio > 2.5 (ultra-wide panoramas)

```python
from PIL import Image

def passes_quality_check(image: Image.Image, min_dim=800, max_aspect_ratio=2.5):
    w, h = image.size
    if min(w, h) < min_dim:
        return False
    if max(w, h) / min(w, h) > max_aspect_ratio:
        return False
    return True
```

### 6.2 CLIP Relevance Scoring (key quality gate)

Use `openai/clip-vit-base-patch32` via HuggingFace transformers (CPU sufficient). Compute cosine similarity between image and text prompt.

**Text prompt:** `"a photo of {destination name}, {destination type, e.g. 'a famous landmark' / 'a coastal town' / 'a mountain village'}"`

```python
from transformers import CLIPProcessor, CLIPModel
import torch

model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")

def relevance_score(image, place_name, place_type=""):
    text = f"a photo of {place_name}, {place_type}".strip()
    inputs = processor(text=[text], images=image, return_tensors="pt", padding=True)
    outputs = model(**inputs)
    score = outputs.logits_per_image.softmax(dim=1)[0][0].item()
    return score
```

**Threshold:** Reject any image scoring below 0.22–0.25 raw cosine similarity (tunable).

### 6.3 Perceptual-Hash Deduplication

Prevent same/near-duplicate photo appearing across destinations.

```python
import imagehash
from PIL import Image

def phash(image: Image.Image):
    return imagehash.phash(image)

def is_duplicate(new_hash, existing_hashes, threshold=5):
    return any(new_hash - h <= threshold for h in existing_hashes)
```

Store hashes in Redis set `img:hashes:{place_id}`.

### 6.4 NSFW / Content Moderation

Use `Falconsai/nsfw_image_detection` (HuggingFace, free, CPU-friendly).

```python
from transformers import pipeline

nsfw_classifier = pipeline("image-classification", model="Falconsai/nsfw_image_detection")

def is_safe(image):
    result = nsfw_classifier(image)
    top = max(result, key=lambda x: x['score'])
    return not (top['label'].lower() == 'nsfw' and top['score'] > 0.5)
```

### 6.5 Smart Crop / Aspect Normalization

Normalize final images to app's card aspect ratio (e.g., 4:3). Use `smartcrop` library or center-crop fallback.

```python
import smartcrop
from PIL import Image

sc = smartcrop.SmartCrop()
def smart_crop(image: Image.Image, target_w=800, target_h=600):
    result = sc.crop(image, width=target_w, height=target_h)
    box = result['top_crop']
    return image.crop((box['x'], box['y'], box['x'] + box['width'], box['y'] + box['height']))
```

---

## 7. Caching & Serving (Stage 3)

Following existing Redis cache pattern (`cache/redis_cache.py`):

| Aspect | Design |
|--------|--------|
| **Cache key** | `img:{place_id}` where `place_id` = Wikidata QID if available, else normalized slug of name+coordinates |
| **Cache value** | JSON: `{url, source, license, attribution, clip_score, width, height, timestamp, verified}` |
| **TTL** | 30 days (configurable via `IMAGE_CACHE_TTL_SECONDS`) |
| **Refresh** | Manual trigger via API/CLI; no automatic background refresh |
| **Dedup hashes** | Redis set `img:hashes:{place_id}` for perceptual hash comparison |
| **Fallback** | If Redis unavailable, fall through to source waterfall (graceful degradation) |

---

## 8. Data Models

### New models (in `images/models.py`)

```python
class ImageCandidate(BaseModel):
    """A raw candidate image from a source, before validation."""
    url: str
    source: str  # "wikidata", "wikimedia_commons", "wikipedia", "openverse", "mapillary", "unsplash", "pexels"
    license: str | None = None
    attribution: str | None = None
    width: int | None = None
    height: int | None = None
    verified: bool = True  # False for generic/stock fallback images


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
```

### Extended existing model (in `domain/models.py`)

```python
class PlaceImage(BaseModel):
    place_name: str
    image_query: str
    image_url: str | None = None
    source: str | None = None
    # New fields:
    license: str | None = None
    attribution: str | None = None
    clip_score: float | None = None
    verified: bool = False
    width: int | None = None
    height: int | None = None
```

---

## 9. New Configuration Settings

Add to `config/settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `image_clip_threshold` | 0.22 | Minimum CLIP cosine similarity score |
| `image_min_resolution` | 800 | Minimum shortest-side dimension in pixels |
| `image_max_aspect_ratio` | 2.5 | Maximum allowed aspect ratio |
| `image_cache_ttl_seconds` | 2592000 | Cache TTL (30 days) |
| `image_dedup_threshold` | 5 | Maximum pHash hamming distance for dedup |
| `image_nsfw_threshold` | 0.5 | NSFW classifier confidence threshold |
| `image_smart_crop_enabled` | True | Enable smart cropping |
| `image_mapillary_token` | None | Mapillary free API token (optional) |
| `image_openverse_enabled` | True | Enable Openverse source |

---

## 10. New Dependencies

Add to `pyproject.toml`:

```
torch = ">=2.0"
transformers = ">=4.30"
Pillow = ">=10.0"
imagehash = ">=4.3"
smartcrop = ">=1.0"
```

Note: `torch` is heavy (~2GB). For production deployment, consider using `torch-cpu` variant only. For local development, full torch is fine.

---

## 11. Error Handling

- Each source function catches exceptions and returns empty list (never raises)
- Post-processing stages return `None` on rejection (short-circuit)
- Redis cache falls through to source waterfall if unavailable
- Pipeline always returns a result (may be `image_url=None` if all sources fail)
- All errors logged at WARNING level (non-fatal for plan generation)

---

## 12. Testing Strategy

| Test | Type | What it verifies |
|------|------|-----------------|
| Source resolution | Unit | Each source function returns valid `ImageCandidate` objects |
| Quality filtering | Unit | Images below min resolution are rejected |
| CLIP scoring | Unit | Score calculation and threshold application |
| Dedup detection | Unit | Near-duplicate images are caught |
| NSFW detection | Unit | Unsafe images are rejected |
| Pipeline integration | Integration | End-to-end: name → image URL with all stages |
| Cache hit/miss | Integration | Cached images are returned; uncached trigger waterfall |
| Fallback chain | Integration | Source failure cascades to next source |

---

## 13. Build Order

1. Implement Wikidata → Commons resolver (5.1–5.2) end-to-end for a single test place
2. Add Wikipedia REST fallback (5.3) and Openverse fallback (5.4)
3. Implement CLIP relevance scoring (6.2) and wire into waterfall
4. Add quality filtering (6.1), dedup (6.3), and NSFW check (6.4)
5. Add smart crop (6.5) as final formatting step
6. Build Redis cache layer (Stage 3)
7. Add Unsplash/Pexels as absolute last-resort fallback (5.6)
8. Rewrite `api/images.py` to use new pipeline
9. Extend `PlaceImage` model in `domain/models.py`
10. Add configuration settings to `config/settings.py`
11. Batch-run pipeline against test destinations, tune thresholds

---

## 14. Notes & Caveats

- **All sources are free at reasonable scale.** Openverse and Mapillary offer optional free API keys for higher rate limits.
- **Always send a descriptive User-Agent header** on Wikimedia/Wikipedia requests (required by their API etiquette policy).
- **Coverage gap:** Small local businesses (specific cafés, boutique hotels) rarely have Wikidata/Commons coverage. Openverse and Mapillary are best free bets for these; Unsplash/Pexels generic shots as final fallback.
- **Legal:** CC0/Public Domain images need no attribution; CC-BY and CC-BY-SA do — store and display attribution text.
- **torch is heavy (~2GB).** For production, consider torch-cpu variant. For development, full torch is fine.

---

## 15. Open Questions

1. **CLIP model selection:** `openai/clip-vit-base-patch32` is the default. Should we support alternative models (e.g., `openai/clip-vit-large-patch14`) for higher accuracy at the cost of speed?
2. **Smart crop library:** `smartcrop` is Python. Should we use a more actively maintained alternative?
3. **Background refresh:** The spec says no automatic refresh. Should we add a scheduled task to re-validate cached images periodically?
