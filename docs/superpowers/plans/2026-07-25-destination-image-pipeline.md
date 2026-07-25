# Destination Image Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing Unsplash/Pexels image system with a free, multi-source pipeline that fetches accurate, high-quality photos using a waterfall of free sources validated by CLIP relevance scoring and post-processing.

**Architecture:** A new `images/` package with 6 modules: models (Pydantic data structures), sources (6 async source fetchers), processor (5-stage post-processing pipeline), cache (Redis wrapper), pipeline (orchestrator), and `__init__.py` (public API). The existing `api/images.py` is rewritten to delegate to this new pipeline.

**Tech Stack:** Python 3.14, httpx (async HTTP), Pillow (image manipulation), transformers + torch (CLIP + NSFW), imagehash (dedup), smartcrop (cropping), Redis (caching), Pydantic (models).

## Global Constraints

- Python >= 3.10 (project uses `|` union syntax)
- Pydantic v2 (project uses `BaseModel` with `Field`)
- Async-first: all source fetchers are async (`httpx.AsyncClient`)
- Redis caching follows existing `cache/redis_cache.py` pattern (lazy init, graceful degradation)
- User-Agent header required for Wikimedia APIs: `"AgenticTravelPlanner/1.0 (https://github.com/agentic-travel-planner)"`
- CLIP model: `openai/clip-vit-base-patch32` (CPU sufficient)
- NSFW model: `Falconsai/nsfw_image_detection`
- All source functions catch exceptions and return empty lists (never raise)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/agentic_tour_planner/images/__init__.py` | Public API: `resolve_images(places) -> list[ImageResult]` |
| `src/agentic_tour_planner/images/models.py` | `ImageCandidate`, `ProcessedImage`, `ImageResult` Pydantic models |
| `src/agentic_tour_planner/images/sources.py` | 6 async source functions: wikidata, wikimedia_commons, wikipedia, openverse, mapillary, stock |
| `src/agentic_tour_planner/images/processor.py` | 5-stage post-processing: quality, CLIP, dedup, NSFW, crop |
| `src/agentic_tour_planner/images/cache.py` | Redis cache layer wrapping existing `RedisCache` |
| `src/agentic_tour_planner/images/pipeline.py` | Orchestrator: waterfall → processor → cache |
| `tests/unit/test_image_models.py` | Unit tests for models |
| `tests/unit/test_image_sources.py` | Unit tests for source fetchers |
| `tests/unit/test_image_processor.py` | Unit tests for post-processing |
| `tests/unit/test_image_cache.py` | Unit tests for cache layer |
| `tests/unit/test_image_pipeline.py` | Integration tests for full pipeline |
| `src/agentic_tour_planner/api/images.py` | Rewrite to delegate to new pipeline |
| `src/agentic_tour_planner/domain/models.py` | Extend `PlaceImage` with new fields |
| `src/agentic_tour_planner/config/settings.py` | Add image-related settings |
| `pyproject.toml` | Add new dependencies |

---

### Task 1: Create image models

**Files:**
- Create: `src/agentic_tour_planner/images/__init__.py`
- Create: `src/agentic_tour_planner/images/models.py`
- Create: `tests/unit/test_image_models.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `ImageCandidate`, `ProcessedImage`, `ImageResult` classes

- [ ] **Step 1: Write failing tests for models**

```python
# tests/unit/test_image_models.py
"""Unit tests for image pipeline models."""
from __future__ import annotations

import pytest
from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage, ImageResult


def test_image_candidate_minimal():
    c = ImageCandidate(url="https://example.com/img.jpg", source="wikidata")
    assert c.url == "https://example.com/img.jpg"
    assert c.source == "wikidata"
    assert c.license is None
    assert c.attribution is None
    assert c.width is None
    assert c.height is None
    assert c.verified is True


def test_image_candidate_full():
    c = ImageCandidate(
        url="https://example.com/img.jpg",
        source="openverse",
        license="CC-BY",
        attribution="Photo by Alice",
        width=1920,
        height=1080,
        verified=False,
    )
    assert c.license == "CC-BY"
    assert c.verified is False


def test_processed_image():
    p = ProcessedImage(
        url="https://example.com/img.jpg",
        source="wikidata",
        clip_score=0.35,
        width=800,
        height=600,
    )
    assert p.clip_score == 0.35
    assert p.verified is True


def test_image_result_no_image():
    r = ImageResult(place_name="Tokyo Tower")
    assert r.image_url is None
    assert r.verified is False


def test_image_result_with_image():
    r = ImageResult(
        place_name="Eiffel Tower",
        image_url="https://example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.42,
        verified=True,
    )
    assert r.image_url == "https://example.com/eiffel.jpg"
    assert r.verified is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_tour_planner.images'`

- [ ] **Step 3: Create the models module**

Create `src/agentic_tour_planner/images/__init__.py`:
```python
"""Destination image pipeline — free, multi-source image fetching with validation."""
```

Create `src/agentic_tour_planner/images/models.py`:
```python
"""Pydantic models for the destination image pipeline."""
from __future__ import annotations

from pydantic import BaseModel, Field


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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_models.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/images/ tests/unit/test_image_models.py
git commit -m "feat(images): add image pipeline models (ImageCandidate, ProcessedImage, ImageResult)"
```

---

### Task 2: Add configuration settings

**Files:**
- Modify: `src/agentic_tour_planner/config/settings.py`
- Create: `tests/unit/test_image_settings.py`

**Interfaces:**
- Consumes: existing `Settings` class
- Produces: 9 new settings fields accessible via `get_settings()`

- [ ] **Step 1: Write failing tests for settings**

```python
# tests/unit/test_image_settings.py
"""Unit tests for image pipeline settings."""
from __future__ import annotations

import os
import pytest
from agentic_tour_planner.config.settings import Settings


def test_image_settings_defaults():
    s = Settings()
    assert s.image_clip_threshold == 0.22
    assert s.image_min_resolution == 800
    assert s.image_max_aspect_ratio == 2.5
    assert s.image_cache_ttl_seconds == 2592000
    assert s.image_dedup_threshold == 5
    assert s.image_nsfw_threshold == 0.5
    assert s.image_smart_crop_enabled is True
    assert s.image_mapillary_token is None
    assert s.image_openverse_enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_settings.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'image_clip_threshold'`

- [ ] **Step 3: Add settings to Settings class**

In `src/agentic_tour_planner/config/settings.py`, add these fields to the `Settings` class (after the existing fields):

```python
    # ── Image pipeline ──────────────────────────────────────────────
    image_clip_threshold: float = 0.22
    image_min_resolution: int = 800
    image_max_aspect_ratio: float = 2.5
    image_cache_ttl_seconds: int = 2592000  # 30 days
    image_dedup_threshold: int = 5
    image_nsfw_threshold: float = 0.5
    image_smart_crop_enabled: bool = True
    image_mapillary_token: str | None = None
    image_openverse_enabled: bool = True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_settings.py -v`
Expected: 1 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/config/settings.py tests/unit/test_image_settings.py
git commit -m "feat(config): add image pipeline settings (CLIP threshold, resolution, cache TTL, etc.)"
```

---

### Task 3: Implement Wikidata + Wikimedia Commons source

**Files:**
- Create: `src/agentic_tour_planner/images/sources.py`
- Create: `tests/unit/test_image_sources.py`

**Interfaces:**
- Consumes: `ImageCandidate` from Task 1, `Settings` from Task 2
- Produces: `fetch_wikidata()`, `fetch_wikimedia_commons()` async functions returning `list[ImageCandidate]`

- [ ] **Step 1: Write failing tests for Wikidata source**

```python
# tests/unit/test_image_sources.py
"""Unit tests for image source fetchers."""
from __future__ import annotations

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from agentic_tour_planner.images.models import ImageCandidate
from agentic_tour_planner.images.sources import fetch_wikidata, fetch_wikimedia_commons


@pytest.mark.asyncio
async def test_fetch_wikidata_returns_candidates():
    """Wikidata source should return ImageCandidate objects."""
    # Mock the Wikidata search API response
    search_response = {
        "search": [{"id": "Q243", "label": "Eiffel Tower", "description": "wrought iron lattice tower"}]
    }
    # Mock the entity data response with P18 claim
    entity_response = {
        "entities": {
            "Q243": {
                "claims": {
                    "P18": [{"mainsnak": {"datavalue": {"value": "Tour Eiffel Wikimedia Commons.jpg"}}}]
                }
            }
        }
    }
    # Mock the Commons imageinfo response
    imageinfo_response = {
        "query": {
            "pages": {
                "12345": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg/800px-Tour_Eiffel_Wikimedia_Commons.jpg",
                            "width": 800,
                            "height": 1200,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "John Doe"},
                            },
                        }
                    ]
                }
            }
        }
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        side_effect=[
            MagicMock(status_code=200, json=lambda: search_response),
            MagicMock(status_code=200, json=lambda: entity_response),
            MagicMock(status_code=200, json=lambda: imageinfo_response),
        ]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikidata("Eiffel Tower")

    assert len(candidates) == 1
    c = candidates[0]
    assert isinstance(c, ImageCandidate)
    assert c.source == "wikidata"
    assert "Tour_Eiffel" in c.url
    assert c.license == "CC BY-SA 4.0"
    assert c.attribution == "John Doe"
    assert c.verified is True


@pytest.mark.asyncio
async def test_fetch_wikidata_no_results():
    """Wikidata source should return empty list when no entity found."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=200, json=lambda: {"search": []}))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikidata("Nonexistent Place XYZ")

    assert candidates == []


@pytest.mark.asyncio
async def test_fetch_wikimedia_commons_returns_candidates():
    """Wikimedia Commons source should return ImageCandidate objects."""
    cat_response = {
        "query": {
            "categorymembers": [
                {"title": "File:Eiffel_Tower_1.jpg"},
                {"title": "File:Eiffel_Tower_2.jpg"},
            ]
        }
    }
    imageinfo_response = {
        "query": {
            "pages": {
                "100": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Eiffel_Tower_1.jpg/800px-Eiffel_Tower_1.jpg",
                            "width": 800,
                            "height": 1200,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "Jane Smith"},
                            },
                        }
                    ]
                },
                "101": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f1/Eiffel_Tower_2.jpg/800px-Eiffel_Tower_2.jpg",
                            "width": 800,
                            "height": 1200,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Artist": {"value": "Bob Jones"},
                            },
                        }
                    ]
                },
            }
        }
    }

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(
        side_effect=[
            MagicMock(status_code=200, json=lambda: cat_response),
            MagicMock(status_code=200, json=lambda: imageinfo_response),
        ]
    )
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("agentic_tour_planner.images.sources.httpx.AsyncClient", return_value=mock_client):
        candidates = await fetch_wikimedia_commons("Eiffel Tower")

    assert len(candidates) == 2
    assert all(c.source == "wikimedia_commons" for c in candidates)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_sources.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError: cannot import name 'fetch_wikidata'`

- [ ] **Step 3: Implement Wikidata + Wikimedia Commons sources**

Create `src/agentic_tour_planner/images/sources.py`:

```python
"""Async source fetchers for the destination image pipeline.

Each function returns a list of ImageCandidate objects. On any error,
functions catch exceptions and return an empty list (never raise).
"""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from agentic_tour_planner.images.models import ImageCandidate
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_USER_AGENT = "AgenticTravelPlanner/1.0 (https://github.com/agentic-travel-planner)"
_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_WIKIPEDIA_REST = "https://en.wikipedia.org/api/rest_v1/page/summary"
_OPENVERSE_API = "https://api.openverse.org/v1/images"


def _make_candidate(
    url: str,
    source: str,
    width: int | None = None,
    height: int | None = None,
    license_name: str | None = None,
    attribution: str | None = None,
    verified: bool = True,
) -> ImageCandidate:
    return ImageCandidate(
        url=url,
        source=source,
        width=width,
        height=height,
        license=license_name,
        attribution=attribution,
        verified=verified,
    )


# ── 5.1 Wikidata (Primary) ─────────────────────────────────────────


async def fetch_wikidata(place_name: str) -> list[ImageCandidate]:
    """Resolve a place name to a Wikidata entity and return its P18 image."""
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=15
        ) as client:
            # Step 1: Search for the entity
            search_resp = await client.get(
                _WIKIDATA_API,
                params={
                    "action": "wbsearchentities",
                    "search": place_name,
                    "language": "en",
                    "format": "json",
                    "type": "item",
                    "limit": 1,
                },
            )
            search_resp.raise_for_status()
            results = search_resp.json().get("search", [])
            if not results:
                return []

            qid = results[0]["id"]

            # Step 2: Fetch entity data with P18 claim
            entity_resp = await client.get(
                f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
            )
            entity_resp.raise_for_status()
            entity_data = entity_resp.json()
            claims = (
                entity_data.get("entities", {}).get(qid, {}).get("claims", {})
            )
            p18_claims = claims.get("P18", [])
            if not p18_claims:
                return []

            filename = (
                p18_claims[0]
                .get("mainsnak", {})
                .get("datavalue", {})
                .get("value", "")
            )
            if not filename:
                return []

            # Step 3: Convert filename to direct URL via Commons imageinfo
            return await _commons_imageinfo_to_candidates(client, filename, "wikidata")

    except Exception as exc:
        logger.warning(f"fetch_wikidata failed for {place_name!r}: {exc}")
        return []


# ── 5.2 Wikimedia Commons Category Search (Fallback #1) ─────────────


async def fetch_wikimedia_commons(place_name: str) -> list[ImageCandidate]:
    """Search Wikimedia Commons category for candidate images."""
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=15
        ) as client:
            # Search for category members
            cat_resp = await client.get(
                _COMMONS_API,
                params={
                    "action": "query",
                    "list": "categorymembers",
                    "cmtitle": f"Category:{place_name}",
                    "cmtype": "file",
                    "cmlimit": 10,
                    "format": "json",
                },
            )
            cat_resp.raise_for_status()
            members = cat_resp.json().get("query", {}).get("categorymembers", [])
            if not members:
                return []

            # Get imageinfo for all files
            titles = "|".join(m["title"] for m in members[:10])
            return await _commons_imageinfo_to_candidates(client, titles, "wikimedia_commons")

    except Exception as exc:
        logger.warning(f"fetch_wikimedia_commons failed for {place_name!r}: {exc}")
        return []


# ── 5.3 Wikipedia REST API — Lead Image (Fallback #2) ───────────────


async def fetch_wikipedia(place_name: str) -> list[ImageCandidate]:
    """Fetch the lead image from a Wikipedia article summary."""
    try:
        # Normalize page title (spaces to underscores)
        page_title = place_name.replace(" ", "_")

        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=10
        ) as client:
            resp = await client.get(f"{_WIKIPEDIA_REST}/{quote(page_title)}")
            if resp.status_code != 200:
                return []
            data = resp.json()

            # Try originalimage first, then thumbnail
            img = data.get("originalimage") or data.get("thumbnail")
            if not img or not img.get("source"):
                return []

            return [
                _make_candidate(
                    url=img["source"],
                    source="wikipedia",
                    width=img.get("width"),
                    height=img.get("height"),
                    license_name=data.get("license", {}).get("name"),
                    verified=True,
                )
            ]

    except Exception as exc:
        logger.warning(f"fetch_wikipedia failed for {place_name!r}: {exc}")
        return []


# ── 5.4 Openverse (Fallback #3) ────────────────────────────────────


async def fetch_openverse(place_name: str) -> list[ImageCandidate]:
    """Search Openverse for CC-licensed images."""
    from agentic_tour_planner.config.settings import get_settings

    settings = get_settings()
    if not settings.image_openverse_enabled:
        return []

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=15
        ) as client:
            resp = await client.get(
                _OPENVERSE_API,
                params={
                    "q": place_name,
                    "license_type": "commercial",
                    "mature": "false",
                    "page_size": 5,
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

            candidates = []
            safe_licenses = {"cc0", "pdm", "by", "by-sa"}
            for r in results:
                lic = (r.get("license") or "").lower()
                if lic not in safe_licenses:
                    continue
                candidates.append(
                    _make_candidate(
                        url=r.get("url", ""),
                        source="openverse",
                        width=r.get("width"),
                        height=r.get("height"),
                        license_name=r.get("license"),
                        attribution=r.get("creator"),
                        verified=True,
                    )
                )
            return candidates

    except Exception as exc:
        logger.warning(f"fetch_openverse failed for {place_name!r}: {exc}")
        return []


# ── 5.5 Mapillary (Optional Fallback #4) ────────────────────────────


async def fetch_mapillary(
    place_name: str, lat: float | None = None, lng: float | None = None
) -> list[ImageCandidate]:
    """Search Mapillary for street-level images near coordinates."""
    from agentic_tour_planner.config.settings import get_settings

    settings = get_settings()
    token = settings.image_mapillary_token
    if not token or lat is None or lng is None:
        return []

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT}, timeout=15
        ) as client:
            resp = await client.get(
                "https://graph.mapillary.com/images",
                params={
                    "fields": "id,thumb_2048_url,width,height",
                    "closeto": f"{lng},{lat}",
                    "radius": 250,
                    "access_token": token,
                    "limit": 5,
                },
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])

            return [
                _make_candidate(
                    url=img.get("thumb_2048_url", ""),
                    source="mapillary",
                    width=img.get("width"),
                    height=img.get("height"),
                    verified=False,  # street-level, not place-verified
                )
                for img in data
                if img.get("thumb_2048_url")
            ]

    except Exception as exc:
        logger.warning(f"fetch_mapillary failed for {place_name!r}: {exc}")
        return []


# ── 5.6 Unsplash/Pexels — Generic Mood Fallback (Last Resort) ──────


async def fetch_stock(place_name: str, place_type: str = "") -> list[ImageCandidate]:
    """Fetch generic mood photos from Unsplash or Pexels as last resort."""
    from agentic_tour_planner.config.settings import get_settings

    settings = get_settings()
    candidates = []

    # Try Unsplash
    if settings.unsplash_access_key:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _USER_AGENT}, timeout=10
            ) as client:
                resp = await client.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": place_type or place_name, "per_page": 3},
                    headers={"Authorization": f"Client-ID {settings.unsplash_access_key}"},
                )
                resp.raise_for_status()
                for photo in resp.json().get("results", [])[:3]:
                    urls = photo.get("urls", {})
                    candidates.append(
                        _make_candidate(
                            url=urls.get("regular", ""),
                            source="unsplash",
                            width=photo.get("width"),
                            height=photo.get("height"),
                            license_name="Unsplash License",
                            attribution=photo.get("user", {}).get("name"),
                            verified=False,
                        )
                    )
        except Exception as exc:
            logger.warning(f"Unsplash fetch failed for {place_name!r}: {exc}")

    # Try Pexels
    if settings.pexels_api_key:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _USER_AGENT}, timeout=10
            ) as client:
                resp = await client.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": place_type or place_name, "per_page": 3},
                    headers={"Authorization": settings.pexels_api_key},
                )
                resp.raise_for_status()
                for photo in resp.json().get("photos", [])[:3]:
                    src = photo.get("src", {})
                    candidates.append(
                        _make_candidate(
                            url=src.get("large", ""),
                            source="pexels",
                            width=photo.get("width"),
                            height=photo.get("height"),
                            license_name="Pexels License",
                            attribution=photo.get("photographer"),
                            verified=False,
                        )
                    )
        except Exception as exc:
            logger.warning(f"Pexels fetch failed for {place_name!r}: {exc}")

    return candidates


# ── Internal helpers ─────────────────────────────────────────────────


async def _commons_imageinfo_to_candidates(
    client: httpx.AsyncClient,
    titles: str,
    source: str,
) -> list[ImageCandidate]:
    """Fetch imageinfo from Wikimedia Commons for one or more file titles."""
    resp = await client.get(
        _COMMONS_API,
        params={
            "action": "query",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url|size|extmetadata",
            "format": "json",
        },
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})

    candidates = []
    for page in pages.values():
        for info in page.get("imageinfo", []):
            url = info.get("url", "")
            if not url:
                continue
            ext = info.get("extmetadata", {})
            candidates.append(
                _make_candidate(
                    url=url,
                    source=source,
                    width=info.get("width"),
                    height=info.get("height"),
                    license_name=ext.get("LicenseShortName", {}).get("value"),
                    attribution=ext.get("Artist", {}).get("value"),
                    verified=True,
                )
            )
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_sources.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/images/sources.py tests/unit/test_image_sources.py
git commit -m "feat(images): add Wikidata, Wikimedia Commons, Wikipedia, Openverse, Mapillary, and stock source fetchers"
```

---

### Task 4: Implement post-processing pipeline

**Files:**
- Create: `src/agentic_tour_planner/images/processor.py`
- Create: `tests/unit/test_image_processor.py`

**Interfaces:**
- Consumes: `ImageCandidate` from Task 1, `Settings` from Task 2
- Produces: `process_image()` function returning `ProcessedImage | None`

- [ ] **Step 1: Write failing tests for processor**

```python
# tests/unit/test_image_processor.py
"""Unit tests for image post-processing pipeline."""
from __future__ import annotations

import io
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image

from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage
from agentic_tour_planner.images.processor import (
    passes_quality_check,
    process_image,
)


def _make_test_image(width: int = 1000, height: int = 800) -> Image.Image:
    """Create a simple test image of given dimensions."""
    return Image.new("RGB", (width, height), color=(128, 64, 32))


def test_quality_check_passes():
    img = _make_test_image(1000, 800)
    assert passes_quality_check(img) is True


def test_quality_check_rejects_small():
    img = _make_test_image(400, 300)
    assert passes_quality_check(img) is False


def test_quality_check_rejects_extreme_aspect():
    img = _make_test_image(5000, 100)  # 50:1 ratio
    assert passes_quality_check(img) is False


def test_quality_check_passes_wide():
    img = _make_test_image(1920, 1080)  # ~1.78 ratio
    assert passes_quality_check(img) is True


@pytest.mark.asyncio
async def test_process_image_rejects_low_res():
    """process_image should return None for images below min resolution."""
    candidate = ImageCandidate(
        url="https://example.com/small.jpg",
        source="wikidata",
    )
    # Mock httpx to return a small image
    small_img = _make_test_image(400, 300)
    buf = io.BytesIO()
    small_img.save(buf, format="JPEG")
    buf.seek(0)

    mock_resp = MagicMock()
    mock_resp.content = buf.getvalue()
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = MagicMock(return_value=mock_client)
    mock_client.__aexit__ = MagicMock(return_value=False)

    with patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client):
        result = await process_image(candidate, "Eiffel Tower")

    assert result is None


@pytest.mark.asyncio
async def test_process_image_passes_quality():
    """process_image should return ProcessedImage for valid images (mocking CLIP)."""
    candidate = ImageCandidate(
        url="https://example.com/good.jpg",
        source="wikidata",
        width=1920,
        height=1080,
    )
    good_img = _make_test_image(1920, 1080)
    buf = io.BytesIO()
    good_img.save(buf, format="JPEG")
    buf.seek(0)

    mock_resp = MagicMock()
    mock_resp.content = buf.getvalue()
    mock_resp.status_code = 200

    mock_client = MagicMock()
    mock_client.get = MagicMock(return_value=mock_resp)
    mock_client.__aenter__ = MagicMock(return_value=mock_client)
    mock_client.__aexit__ = MagicMock(return_value=False)

    # Mock CLIP scoring to return high score
    mock_score = MagicMock(return_value=0.35)

    # Mock NSFW to return safe
    mock_nsfw = MagicMock(return_value=True)

    # Mock dedup to return not duplicate
    mock_dedup = MagicMock(return_value=False)

    with (
        patch("agentic_tour_planner.images.processor.httpx.AsyncClient", return_value=mock_client),
        patch("agentic_tour_planner.images.processor._clip_score", mock_score),
        patch("agentic_tour_planner.images.processor._is_nsfw", mock_nsfw),
        patch("agentic_tour_planner.images.processor._is_duplicate", mock_dedup),
        patch("agentic_tour_planner.images.processor._smart_crop", lambda img, w, h: img),
    ):
        result = await process_image(candidate, "Eiffel Tower")

    assert result is not None
    assert isinstance(result, ProcessedImage)
    assert result.clip_score == 0.35
    assert result.source == "wikidata"
    assert result.verified is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_processor.py -v`
Expected: FAIL — `ImportError: cannot import name 'passes_quality_check'`

- [ ] **Step 3: Implement post-processing pipeline**

Create `src/agentic_tour_planner/images/processor.py`:

```python
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

    settings = get_settings()
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
    settings = get_settings()

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_processor.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/images/processor.py tests/unit/test_image_processor.py
git commit -m "feat(images): add post-processing pipeline (quality, CLIP, dedup, NSFW, crop)"
```

---

### Task 5: Implement Redis cache layer

**Files:**
- Create: `src/agentic_tour_planner/images/cache.py`
- Create: `tests/unit/test_image_cache.py`

**Interfaces:**
- Consumes: `ImageResult` from Task 1, existing `RedisCache` from `cache/redis_cache.py`
- Produces: `get_cached_image()`, `set_cached_image()`, `get_dedup_hashes()`, `add_dedup_hash()` functions

- [ ] **Step 1: Write failing tests for cache**

```python
# tests/unit/test_image_cache.py
"""Unit tests for image cache layer."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

from agentic_tour_planner.images.models import ImageResult
from agentic_tour_planner.images.cache import (
    get_cached_image,
    set_cached_image,
    get_dedup_hashes,
    add_dedup_hash,
    _cache_key,
    _hash_key,
)


def test_cache_key_format():
    assert _cache_key("Q243") == "img:Q243"
    assert _cache_key("eiffel-tower") == "img:eiffel-tower"


def test_hash_key_format():
    assert _hash_key("Q243") == "img:hashes:Q243"


@pytest.mark.asyncio
async def test_get_cached_image_returns_none_when_disabled():
    """Cache should return None when Redis is disabled."""
    with patch("agentic_tour_planner.images.cache.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(redis_cache_enabled=False)
        result = await get_cached_image("Q243")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_image_returns_none_on_miss():
    """Cache should return None on cache miss."""
    with patch("agentic_tour_planner.images.cache.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(redis_cache_enabled=True)
        with patch("agentic_tour_planner.images.cache.RedisCache") as MockCache:
            instance = MockCache.return_value
            instance.get_json = AsyncMock(return_value=None)
            result = await get_cached_image("Q243")
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_image_returns_result_on_hit():
    """Cache should return ImageResult on cache hit."""
    cached_data = {
        "place_name": "Eiffel Tower",
        "image_url": "https://example.com/eiffel.jpg",
        "source": "wikidata",
        "license": "CC BY-SA 4.0",
        "attribution": "John Doe",
        "clip_score": 0.42,
        "verified": True,
        "width": 800,
        "height": 600,
        "timestamp": datetime.utcnow().isoformat(),
    }
    with patch("agentic_tour_planner.images.cache.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(redis_cache_enabled=True)
        with patch("agentic_tour_planner.images.cache.RedisCache") as MockCache:
            instance = MockCache.return_value
            instance.get_json = AsyncMock(return_value=cached_data)
            result = await get_cached_image("Q243")
    assert result is not None
    assert result.place_name == "Eiffel Tower"
    assert result.image_url == "https://example.com/eiffel.jpg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_cache.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_cached_image'`

- [ ] **Step 3: Implement cache layer**

Create `src/agentic_tour_planner/images/cache.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_cache.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/images/cache.py tests/unit/test_image_cache.py
git commit -m "feat(images): add Redis cache layer for image results and dedup hashes"
```

---

### Task 6: Implement pipeline orchestrator

**Files:**
- Create: `src/agentic_tour_planner/images/pipeline.py`
- Update: `src/agentic_tour_planner/images/__init__.py`
- Create: `tests/unit/test_image_pipeline.py`

**Interfaces:**
- Consumes: sources (Task 3), processor (Task 4), cache (Task 5)
- Produces: `resolve_images(places: list[dict]) -> list[ImageResult]` public API

- [ ] **Step 1: Write failing tests for pipeline**

```python
# tests/unit/test_image_pipeline.py
"""Integration tests for the image pipeline orchestrator."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from agentic_tour_planner.images.models import ImageCandidate, ProcessedImage, ImageResult
from agentic_tour_planner.images.pipeline import resolve_images


@pytest.mark.asyncio
async def test_resolve_images_returns_empty_for_empty_input():
    result = await resolve_images([])
    assert result == []


@pytest.mark.asyncio
async def test_resolve_images_returns_result_when_source_and_processing_succeed():
    """Pipeline should return a successful result when source + processor work."""
    candidate = ImageCandidate(
        url="https://example.com/eiffel.jpg",
        source="wikidata",
        width=1920,
        height=1080,
    )
    processed = ProcessedImage(
        url="https://example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.42,
        width=800,
        height=600,
    )

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.fetch_wikidata", new_callable=AsyncMock, return_value=[candidate]),
        patch("agentic_tour_planner.images.pipeline.process_image", new_callable=AsyncMock, return_value=processed),
        patch("agentic_tour_planner.images.pipeline.set_cached_image", new_callable=AsyncMock),
        patch("agentic_tour_planner.images.pipeline.add_dedup_hash", new_callable=AsyncMock),
        patch("agentic_tour_planner.images.pipeline.get_dedup_hashes", new_callable=AsyncMock, return_value=[]),
    ):
        results = await resolve_images([{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}])

    assert len(results) == 1
    r = results[0]
    assert r.place_name == "Eiffel Tower"
    assert r.image_url == "https://example.com/eiffel.jpg"
    assert r.clip_score == 0.42


@pytest.mark.asyncio
async def test_resolve_images_returns_no_image_when_all_sources_fail():
    """Pipeline should return no image when all sources fail."""
    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=None),
        patch("agentic_tour_planner.images.pipeline.fetch_wikidata", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_wikimedia_commons", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_wikipedia", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_openverse", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_mapillary", new_callable=AsyncMock, return_value=[]),
        patch("agentic_tour_planner.images.pipeline.fetch_stock", new_callable=AsyncMock, return_value=[]),
    ):
        results = await resolve_images([{"place_name": "Nonexistent Place", "image_query": "nonexistent"}])

    assert len(results) == 1
    assert results[0].image_url is None


@pytest.mark.asyncio
async def test_resolve_images_uses_cache_when_available():
    """Pipeline should return cached result when available."""
    cached = ImageResult(
        place_name="Eiffel Tower",
        image_url="https://cached.example.com/eiffel.jpg",
        source="wikidata",
        clip_score=0.5,
        verified=True,
    )

    with (
        patch("agentic_tour_planner.images.pipeline.get_cached_image", new_callable=AsyncMock, return_value=cached),
    ):
        results = await resolve_images([{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}])

    assert len(results) == 1
    assert results[0].image_url == "https://cached.example.com/eiffel.jpg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_images'`

- [ ] **Step 3: Implement pipeline orchestrator**

Create `src/agentic_tour_planner/images/pipeline.py`:

```python
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
                from agentic_tour_planner.images.processor import _compute_phash
                from PIL import Image
                import io
                import httpx

                try:
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
```

Update `src/agentic_tour_planner/images/__init__.py`:

```python
"""Destination image pipeline — free, multi-source image fetching with validation."""

from agentic_tour_planner.images.models import ImageCandidate, ImageResult, ProcessedImage
from agentic_tour_planner.images.pipeline import resolve_images

__all__ = [
    "ImageCandidate",
    "ImageResult",
    "ProcessedImage",
    "resolve_images",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_pipeline.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/images/pipeline.py src/agentic_tour_planner/images/__init__.py tests/unit/test_image_pipeline.py
git commit -m "feat(images): add pipeline orchestrator with waterfall, processing, and caching"
```

---

### Task 7: Extend PlaceImage model

**Files:**
- Modify: `src/agentic_tour_planner/domain/models.py`
- Create: `tests/unit/test_image_models_extended.py`

**Interfaces:**
- Consumes: existing `PlaceImage` model
- Produces: Extended `PlaceImage` with new fields

- [ ] **Step 1: Write failing tests for extended model**

```python
# tests/unit/test_image_models_extended.py
"""Tests for extended PlaceImage model."""
from __future__ import annotations

from agentic_tour_planner.domain.models import PlaceImage


def test_place_image_backward_compatible():
    """Old code creating PlaceImage with 4 fields should still work."""
    p = PlaceImage(
        place_name="Eiffel Tower",
        image_query="eiffel tower paris",
        image_url="https://example.com/eiffel.jpg",
        source="unsplash",
    )
    assert p.place_name == "Eiffel Tower"
    assert p.license is None
    assert p.verified is False


def test_place_image_with_new_fields():
    """New fields should be settable."""
    p = PlaceImage(
        place_name="Eiffel Tower",
        image_query="eiffel tower paris",
        image_url="https://example.com/eiffel.jpg",
        source="wikidata",
        license="CC BY-SA 4.0",
        attribution="John Doe",
        clip_score=0.42,
        verified=True,
        width=800,
        height=600,
    )
    assert p.license == "CC BY-SA 4.0"
    assert p.clip_score == 0.42
    assert p.verified is True
    assert p.width == 800
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_models_extended.py -v`
Expected: FAIL — `TypeError: unexpected keyword argument 'license'`

- [ ] **Step 3: Extend PlaceImage model**

In `src/agentic_tour_planner/domain/models.py`, find the `PlaceImage` class and add new fields:

```python
class PlaceImage(BaseModel):
    place_name: str
    image_query: str
    image_url: str | None = None
    source: str | None = None
    # New fields for image pipeline
    license: str | None = None
    attribution: str | None = None
    clip_score: float | None = None
    verified: bool = False
    width: int | None = None
    height: int | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_models_extended.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/domain/models.py tests/unit/test_image_models_extended.py
git commit -m "feat(domain): extend PlaceImage with license, attribution, clip_score, verified, width, height"
```

---

### Task 8: Rewrite api/images.py to use new pipeline

**Files:**
- Rewrite: `src/agentic_tour_planner/api/images.py`
- Create: `tests/unit/test_api_images.py`

**Interfaces:**
- Consumes: `resolve_images` from `images.pipeline`
- Produces: Updated `resolve_images()` function compatible with existing `api/main.py` caller

- [ ] **Step 1: Write failing tests for rewritten API**

```python
# tests/unit/test_api_images.py
"""Tests for the rewritten api/images.py module."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from agentic_tour_planner.api.images import resolve_images
from agentic_tour_planner.domain.models import PlaceImage


@pytest.mark.asyncio
async def test_resolve_images_delegates_to_pipeline():
    """api.images.resolve_images should delegate to images.pipeline.resolve_images."""
    mock_results = [
        {
            "place_name": "Eiffel Tower",
            "image_url": "https://example.com/eiffel.jpg",
            "source": "wikidata",
            "license": "CC BY-SA 4.0",
            "attribution": "John Doe",
            "clip_score": 0.42,
            "verified": True,
            "width": 800,
            "height": 600,
        }
    ]

    with patch(
        "agentic_tour_planner.images.pipeline.resolve_images",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        places = [{"place_name": "Eiffel Tower", "image_query": "eiffel tower"}]
        results = await resolve_images(places)

    assert len(results) == 1
    assert isinstance(results[0], PlaceImage)
    assert results[0].place_name == "Eiffel Tower"
    assert results[0].license == "CC BY-SA 4.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_api_images.py -v`
Expected: FAIL — old code doesn't return PlaceImage with new fields

- [ ] **Step 3: Rewrite api/images.py**

Replace the entire content of `src/agentic_tour_planner/api/images.py`:

```python
"""Image resolution — delegates to the new multi-source image pipeline."""
from __future__ import annotations

from agentic_tour_planner.domain.models import PlaceImage
from agentic_tour_planner.images.pipeline import resolve_images as _pipeline_resolve
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


async def resolve_images(places: list[dict]) -> list[PlaceImage]:
    """Resolve images for a list of places using the multi-source pipeline.

    Each dict should have 'place_name' and optionally 'image_query'.
    Returns a list of PlaceImage objects compatible with the existing API.
    """
    if not places:
        return []

    results = await _pipeline_resolve(places)

    return [
        PlaceImage(
            place_name=r.place_name,
            image_query="",  # original query not stored in ImageResult
            image_url=r.image_url,
            source=r.source,
            license=r.license,
            attribution=r.attribution,
            clip_score=r.clip_score,
            verified=r.verified,
            width=r.width,
            height=r.height,
        )
        for r in results
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_api_images.py -v`
Expected: 1 test PASS

- [ ] **Step 5: Commit**

```bash
git add src/agentic_tour_planner/api/images.py tests/unit/test_api_images.py
git commit -m "feat(api): rewrite images.py to delegate to new multi-source pipeline"
```

---

### Task 9: Add new dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to the `[project] dependencies` list:

```
    "torch>=2.0",
    "transformers>=4.30",
    "Pillow>=10.0",
    "imagehash>=4.3",
    "smartcrop>=1.0",
```

- [ ] **Step 2: Install dependencies**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && uv sync`

- [ ] **Step 3: Verify imports work**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -c "from agentic_tour_planner.images import resolve_images; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add torch, transformers, Pillow, imagehash, smartcrop for image pipeline"
```

---

### Task 10: Run all tests and verify

**Files:** None (verification only)

- [ ] **Step 1: Run all image pipeline tests**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_image_*.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing pipeline tests to ensure no regressions**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/test_pipeline.py -v`
Expected: All tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd /home/prithwijit/programming/python/imp_projects/tour-planner/agentic_travel_planner && .venv/bin/python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -30`
Expected: All tests PASS (or only pre-existing failures unrelated to this feature)

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: finalize image pipeline implementation"
```
