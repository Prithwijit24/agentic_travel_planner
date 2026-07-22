from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import httpx

from agentic_tour_planner.cache.redis_cache import RedisCache
from agentic_tour_planner.domain.models import (
    LiveWebBrief,
    LiveWebSource,
    PlanningRequest,
)
from agentic_tour_planner.ingestion.connectors import SourceConnectors
from agentic_tour_planner.llm.provider import LLMProvider
from agentic_tour_planner.tools.search_provider import (
    SearchHit,
    SearchProvider,
    parse_duration,
    parse_published,
)
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# Per-category search intents so the crawl covers all five required angles.
CATEGORY_QUERIES: dict[str, str] = {
    "path_instructions": "{destination} how to travel between attractions route directions guide",
    "fair_charges": "{destination} attraction entry fees fair charges ticket cost",
    "transport_availability": "{destination} public transport availability bus train metro pass",
    "place_reviews": "{destination} honest reviews of places to visit",
    "daywise_guide": "{destination} day wise itinerary plan guide",
}

_MAX_CRAWL_CHARS = 12000  # bound tokens sent for translation
_TOP_VIDEOS = 2
_TOP_BLOGS = 2
_CUTOFF_DAYS = 730  # last 2 years
_MIN_VIDEO_SECONDS = 10 * 60

_EXTRACT_SYSTEM = (
    "You are extracting structured travel intelligence from mixed-language web sources. "
    "First translate any non-English content to English in your head, then return strict JSON "
    "with exactly these five string keys: "
    "path_instructions, fair_charges, transport_availability, place_reviews, daywise_guide. "
    "Each value is a concise, factual English paragraph drawn ONLY from the sources. "
    "If a source says nothing about a section, use an empty string for that key."
)

_EXTRACT_USER = (
    "Destination: {destination}\n\n"
    "Combined web sources (may be in various languages):\n{combined}\n\n"
    "Translate as needed and return JSON with the five fields."
)


class LiveWebCollector:
    """On-the-fly live web intelligence: search -> crawl blogs/videos -> translate ->
    extract the five required categories into a :class:`LiveWebBrief`.

    Nothing is written to the knowledge base; this is purely live context fed to the
    planner as the authoritative source of truth.
    """

    def __init__(self, llm: LLMProvider, search: SearchProvider | None = None) -> None:
        self.llm = llm
        self.search = search or SearchProvider()
        self.connectors = SourceConnectors()
        self.cache = RedisCache()

    async def collect(self, request: PlanningRequest, provider_override: str | None = None) -> LiveWebBrief:
        cache_key = (
            f"livebrief:{request.destination}:{','.join(request.interests or [])}"
            f":{request.travel_month or ''}"
        )
        try:
            cached = await self.cache.get_json(cache_key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[live-web] cache read failed: {}", exc)
            cached = None
        if cached:
            logger.info("[live-web] cache hit for {}", request.destination)
            return LiveWebBrief(**cached)

        topics = ", ".join(request.interests) if request.interests else "travel"
        video_hits: list[SearchHit] = []
        web_hits: list[SearchHit] = []

        for template in CATEGORY_QUERIES.values():
            query = template.format(destination=request.destination)
            query = f"{query} {topics}".strip()
            video_hits.extend(await self.search.search(query, kind="video", max_results=3))
            web_hits.extend(await self.search.search(query, kind="web", max_results=3))

        # Dedupe video candidates before metadata lookups to avoid redundant
        # YouTube Data API calls; then enrich with official metadata (duration +
        # publish date) so the recency/length filter is actually enforceable.
        videos_unique = self._dedupe(video_hits)
        await self._enrich_video_metadata(videos_unique)
        videos = self._select_videos(videos_unique)
        blogs = self._select_blogs(web_hits)
        logger.info(
            "[live-web] selected %d videos + %d blogs (from %d video / %d web candidates)",
            len(videos), len(blogs), len(video_hits), len(web_hits),
        )

        # Fetch content for every selected source, then translate+extract in ONE
        # combined LLM call (was one translate + one extract per source).
        raw: list[tuple[SearchHit, str]] = []
        media: dict[str, str | None] = {}
        for hit in videos:
            audio_path = await self._download_audio(hit.url)
            media[hit.url] = audio_path
            text = await self._fetch_transcript(hit, audio_path)
            if text:
                raw.append((hit, text))
        for hit in blogs:
            text = await self._crawl(hit)
            if text:
                raw.append((hit, text))

        if not raw:
            logger.info("[live-web] no usable content; returning empty brief")
            return LiveWebBrief()

        combined = "\n\n---\n\n".join(
            f"[{h.kind.upper()}] {h.title} ({h.url})\n{txt}" for h, txt in raw
        )
        brief = await self._extract(request, combined, provider_override)
        brief.sources = [
            LiveWebSource(
                title=h.title,
                url=h.url,
                kind=h.kind,
                audio_path=media.get(h.url),
            )
            for h, _ in raw
        ]
        try:
            await self.cache.set_json(cache_key, brief.model_dump(), ttl=86400)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[live-web] cache write failed: {}", exc)
        return brief

    # ----------------------------------------------------------- selection
    def _select_videos(self, hits: list[SearchHit]) -> list[SearchHit]:
        """Prefer >=10-min recent videos (per spec). Respect the 2-year recency
        rule strictly: never include stale videos. Pad the top 5 with
        recent-but-shorter videos when not enough long ones exist. Only if every
        candidate is stale do we fall back to the longest, so we never starve the
        planner entirely."""
        seen: set[str] = set()
        strict: list[SearchHit] = []
        recent_short: list[SearchHit] = []
        for h in hits:
            if h.url in seen:
                continue
            seen.add(h.url)
            recent = h.published_date is None or not self._too_old(h.published_date)
            long_enough = h.duration_seconds is None or h.duration_seconds >= _MIN_VIDEO_SECONDS
            if recent and long_enough:
                strict.append(h)
            elif recent:
                recent_short.append(h)
        ordered = strict + recent_short
        if not ordered:
            logger.info("[live-web] all video candidates stale; emergency fallback to longest")
            ordered = sorted(hits, key=lambda h: -(h.duration_seconds or 0))
        if len(strict) < _TOP_VIDEOS and recent_short:
            logger.info(
                "[live-web] strict >=%dmin filter left %d videos; padded with %d shorter/recent",
                _MIN_VIDEO_SECONDS // 60, len(strict), len(recent_short),
            )
        return ordered[:_TOP_VIDEOS]

    def _select_blogs(self, hits: list[SearchHit]) -> list[SearchHit]:
        seen: set[str] = set()
        out: list[SearchHit] = []
        for h in hits:
            if h.url in seen:
                continue
            seen.add(h.url)
            out.append(h)
            if len(out) >= _TOP_BLOGS:
                break
        return out

    @staticmethod
    def _too_old(iso_date: str) -> bool:
        try:
            from datetime import date, datetime

            d = datetime.fromisoformat(iso_date).date()
            return (date.today() - d).days > _CUTOFF_DAYS
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _dedupe(hits: list[SearchHit]) -> list[SearchHit]:
        seen: set[str] = set()
        out: list[SearchHit] = []
        for h in hits:
            if h.url in seen:
                continue
            seen.add(h.url)
            out.append(h)
        return out

    # ----------------------------------------------------------- YouTube metadata
    async def _enrich_video_metadata(self, hits: list[SearchHit]) -> None:
        """Fill duration/published-at from the official YouTube Data API so the
        recency/length filter works even when the search provider omitted them
        (SerpAPI/Tavily YouTube results frequently lack this metadata)."""
        key = getattr(self.settings, "youtube_api_key", None) or getattr(
            self.settings, "google_api_key", None
        )
        if not key:
            logger.info("[live-web] no YouTube API key; skipping metadata enrichment")
            return
        for h in hits:
            if h.kind != "video":
                continue
            if h.duration_seconds is not None and h.published_date is not None:
                continue  # already have metadata from the search provider
            vid = self._yt_id(h.url)
            if not vid:
                continue
            try:
                meta = await self.cache.get_json(f"ytmeta:{vid}")
                if meta is None:
                    meta = await self._yt_metadata(vid, key)
                    await self.cache.set_json(f"ytmeta:{vid}", meta, ttl_seconds=86400)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[live-web] YT metadata failed for {}: {}", vid, exc)
                continue
            if meta.get("duration") and h.duration_seconds is None:
                h.duration_seconds = parse_duration(meta["duration"])
            if meta.get("published") and h.published_date is None:
                h.published_date = parse_published(meta["published"])
            desc = (meta.get("description") or "").strip()
            if desc and (not h.snippet or len(h.snippet) < 80):
                h.snippet = desc

    @staticmethod
    async def _yt_metadata(video_id: str, api_key: str) -> dict[str, Any]:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {"part": "contentDetails,snippet", "id": video_id, "key": api_key}
        async with httpx.AsyncClient(timeout=15) as client:
            from agentic_tour_planner.tools.http_util import aretry_get

            r = await aretry_get(client, url, params=params)
            r.raise_for_status()
            items = r.json().get("items") or []
            if not items:
                return {}
            it = items[0]
            return {
                "duration": it.get("contentDetails", {}).get("duration"),
                "published": it.get("snippet", {}).get("publishedAt"),
                "description": it.get("snippet", {}).get("description", ""),
            }

    @staticmethod
    def _yt_id(url: str) -> str | None:
        try:
            return SourceConnectors._extract_youtube_id(url)
        except Exception:  # noqa: BLE001
            return None

    @property
    def settings(self):
        from agentic_tour_planner.config.settings import get_settings

        return get_settings()

    # ----------------------------------------------------------- crawl + translate
    async def _crawl(self, hit: SearchHit) -> str | None:
        try:
            if hit.kind == "video":
                content = await self._fetch_transcript(hit)
            else:
                doc = await self.connectors.fetch_web_document(
                    hit.url,
                    source_id=f"live:{hit.url}",
                    title=hit.title,
                    source_type="web",
                )
                content = (doc.content or "").strip()
            return content[:_MAX_CRAWL_CHARS] if content else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[live-web] crawl failed for {}: {}", hit.url, exc)
            return None

    async def _fetch_transcript(self, hit: SearchHit, audio_path: str | None) -> str | None:
        """Prefer youtube-transcript-api; if it is blocked/empty, transcribe the
        fetched audio via Groq's Whisper translation endpoint; finally fall back
        to the official description. youtube-transcript-api scrapes an
        undocumented anonymous endpoint and is prone to IP/rate limiting, so the
        Groq ASR path is the production-safe transcript source."""
        last: Exception | None = None
        for attempt in range(2):
            try:
                doc = await asyncio.wait_for(
                    self.connectors.fetch_youtube_transcript(hit.url),
                    timeout=15,
                )
                if doc.content and doc.content.strip():
                    return doc.content.strip()
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == 0:
                    await asyncio.sleep(1)
        if audio_path:
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(self._transcribe_audio, audio_path),
                    timeout=60,
                )
                if text:
                    return text
            except asyncio.TimeoutError:
                logger.warning("[live-web] Groq transcription timed out for {}", hit.url)
        logger.warning(
            "[live-web] transcript unavailable for {}: {}; using description",
            hit.url, last,
        )
        return (hit.snippet or "").strip() or None

    # ----------------------------------------------------------- media fetch
    def _media_dir_for(self, url: str) -> Path:
        vid = self._yt_id(url)
        if not vid:
            vid = re.sub(r"\W+", "_", url)[:48]
        d = self.media_root / vid
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _existing(d: Path, prefix: str) -> str | None:
        for f in d.glob(f"{prefix}*"):
            if f.is_file():
                return str(f)
        return None

    async def _download_audio(self, url: str) -> str | None:
        try:
            import yt_dlp
        except Exception as exc:  # pragma: no cover
            logger.warning("[live-web] yt-dlp unavailable: {}", exc)
            return None
        d = self._media_dir_for(url)
        existing = self._existing(d, "audio_")
        if existing:
            return existing
        opts = {
            "outtmpl": str(d / "audio_%(id)s.%(ext)s"),
            "format": "bestaudio[abr<=96]/bestaudio",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        def _run() -> str | None:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                fp = (info.get("requested_downloads") or [{}])[0].get("filepath")
                if not fp:
                    fp = info.get("filepath")
            return fp

        try:
            path = await asyncio.wait_for(asyncio.to_thread(_run), timeout=120)
            return str(path) if path and Path(path).exists() else None
        except asyncio.TimeoutError:
            logger.warning("[live-web] audio download timed out for {}", url)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[live-web] audio download failed for {}: {}", url, exc)
            return None

    def _transcribe_audio(self, path: str) -> str | None:
        try:
            from groq import Groq
        except Exception as exc:  # pragma: no cover
            logger.warning("[live-web] groq SDK unavailable: {}", exc)
            return None
        key = getattr(self.settings, "groqai_api_key", None)
        if not key:
            logger.warning("[live-web] no GROQ_API_KEY; skipping audio transcription")
            return None
        size = Path(path).stat().st_size
        if size > 24 * 1024 * 1024:
            logger.warning("[live-web] audio {} too large ({:.1f}MB) for Groq 25MB limit", path, size / 1e6)
            return None
        try:
            client = Groq(api_key=key)
            with open(path, "rb") as f:
                resp = client.audio.translations.create(
                    file=f,
                    model="whisper-large-v3",
                    response_format="json",
                )
            return (resp.text or "").strip() or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("[live-web] Groq transcription failed: {}", exc)
            return None

    @property
    def media_root(self) -> Path:
        return Path(__file__).resolve().parents[3] / "cache" / "live_media"

    # ----------------------------------------------------------- extract
    async def _extract(
        self,
        request: PlanningRequest,
        combined_text: str,
        provider_override: str | None,
    ) -> LiveWebBrief:
        if not combined_text:
            return LiveWebBrief()
        try:
            data = await self.llm.extract_json(
                _EXTRACT_USER.format(destination=request.destination, combined=combined_text[:40000]),
                system_prompt=_EXTRACT_SYSTEM,
                role="worker",
                provider_override=provider_override,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[live-web] extraction failed: {}", exc)
            return LiveWebBrief()
        return LiveWebBrief(
            path_instructions=data.get("path_instructions", "") or "",
            fair_charges=data.get("fair_charges", "") or "",
            transport_availability=data.get("transport_availability", "") or "",
            place_reviews=data.get("place_reviews", "") or "",
            daywise_guide=data.get("daywise_guide", "") or "",
        )
