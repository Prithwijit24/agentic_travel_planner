"""Async source fetchers for the destination image pipeline.

Each function returns a list of ImageCandidate objects. On any error,
functions catch exceptions and return an empty list (never raise).
"""

from __future__ import annotations

from typing import Any
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


def _sanitize_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _make_candidate(
    url: str,
    source: str,
    width: int | None = None,
    height: int | None = None,
    license_name: str | None = None,
    attribution: str | None = None,
    verified: bool = True,
    clip_score: float | None = None,
) -> ImageCandidate:
    return ImageCandidate(
        url=url,
        source=source,
        width=_sanitize_int(width),
        height=_sanitize_int(height),
        license=license_name,
        attribution=attribution,
        verified=verified,
        clip_score=clip_score,
    )


# ── 5.1 Wikidata (Primary) ─────────────────────────────────────────


async def fetch_wikidata(place_name: str) -> list[ImageCandidate]:
    """Resolve a place name to a Wikidata entity and return its P18 image."""
    try:
        async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=15) as client:
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
            entity_resp = await client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
            entity_resp.raise_for_status()
            entity_data = entity_resp.json()
            claims = entity_data.get("entities", {}).get(qid, {}).get("claims", {})
            p18_claims = claims.get("P18", [])
            if not p18_claims:
                return []

            filename = p18_claims[0].get("mainsnak", {}).get("datavalue", {}).get("value", "")
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
        async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=15) as client:
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

        async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=10) as client:
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
        async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=15, follow_redirects=True) as client:
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


async def fetch_mapillary(place_name: str, lat: float | None = None, lng: float | None = None) -> list[ImageCandidate]:
    """Search Mapillary for street-level images near coordinates."""
    from agentic_tour_planner.config.settings import get_settings

    settings = get_settings()
    token = settings.image_mapillary_token
    if not token or lat is None or lng is None:
        return []

    try:
        async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=15) as client:
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
            async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=10) as client:
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
            async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=10) as client:
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


# ── 5.0 AI Infra Stack /images (Primary — CLIP-scored results) ────


async def fetch_stack_images(place_name: str) -> list[ImageCandidate]:
    """Search images via AI Infra Stack /images endpoint.

    The endpoint performs web search + CLIP reranking in one call,
    returning results with pre-computed clip_score (0-1).
    Fallback chain: DDGS → Unsplash → Pexels.
    """
    from agentic_tour_planner.tools.ai_stack_client import AiStackClient

    stack = AiStackClient()
    try:
        result = await stack.images(
            query=place_name,
            max_results=5,
            use_clip=True,
        )
        images = result.get("images", []) or result.get("results", [])
        candidates = []
        for img in images:
            url = img.get("image_url", "") or img.get("url", "")
            if not url:
                continue
            candidates.append(
                _make_candidate(
                    url=url,
                    source="aistack",
                    width=img.get("width"),
                    height=img.get("height"),
                    license_name=img.get("license"),
                    attribution=img.get("source") or img.get("source_url", ""),
                    verified=True,
                    clip_score=img.get("clip_score"),
                )
            )
        return candidates
    except Exception as exc:
        logger.warning(f"fetch_stack_images failed for {place_name!r}: {exc}")
        return []
    finally:
        stack.close()


# ── 5.0b DuckDuckGo Images (Fallback — no API key needed) ────────────


async def fetch_ddgs_images(place_name: str) -> list[ImageCandidate]:
    """Search DuckDuckGo for images of a place. No API key required."""
    try:
        from ddgs import DDGS

        items = list(DDGS().images(place_name, max_results=5))
        return [
            _make_candidate(
                url=item.get("image") or item.get("thumbnail") or "",
                source="ddgs",
                width=item.get("width"),
                height=item.get("height"),
                license_name=None,  # DDGS doesn't provide license info
                attribution=item.get("source"),
                verified=False,  # Not a curated/open-licensed source
            )
            for item in items
            if item.get("image")
        ]
    except Exception as exc:
        logger.warning(f"fetch_ddgs_images failed for {place_name!r}: {exc}")
        return []


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
