from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from agentic_tour_planner.cache import RedisCache
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.tools.ai_stack_client import AiStackClient
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class SourceConnectors:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.ai_stack = AiStackClient()
        self.cache = RedisCache()
        logger.debug("Initialized SourceConnectors with AiStackClient")

    async def fetch_wikivoyage(self, destination: str) -> SourceDocument:
        slug = destination.strip().replace(" ", "_")
        url = f"https://en.wikivoyage.org/wiki/{slug}"
        logger.info(f"Fetching Wikivoyage page for destination={destination!r} url={url}")
        try:
            result = await self.ai_stack.crawl(url)
            content = result.get("markdown", result.get("content", ""))
        except Exception as e:
            logger.warning(f"AiStackClient crawl failed for {url}: {e}")
            content = ""
        logger.debug(f"Wikivoyage crawl complete content_len={len(content)}")
        return SourceDocument(
            source_id=f"wikivoyage:{slug.lower()}",
            source_type="wikivoyage",
            title=f"{destination} travel guide",
            url=url,
            content=content,
            metadata={"destination": destination, "backend": "ai_stack"},
        )

    async def fetch_web_document(
        self,
        url: str,
        source_id: str,
        title: str,
        source_type: str = "web",
        crawl_backend: str | None = None,  # kept for backward compat, ignored
    ) -> SourceDocument:
        logger.info(f"Fetching web document url={url} source_id={source_id} source_type={source_type}")
        try:
            result = await self.ai_stack.crawl(url)
            content = result.get("markdown", result.get("content", ""))
            final_title = title if title else result.get("title", title)
        except Exception as e:
            logger.warning(f"AiStackClient crawl failed for {url}: {e}")
            content = ""
            final_title = title
        logger.debug(f"Web document fetched title={final_title!r} text_len={len(content)}")
        return SourceDocument(
            source_id=source_id,
            source_type=source_type,  # type: ignore[arg-type]
            title=final_title,
            url=url,
            content=content,
            metadata={"backend": "ai_stack"},
        )

    async def fetch_youtube_transcript(self, url: str) -> SourceDocument:
        video_id = self._extract_youtube_id(url)
        logger.info(f"Fetching YouTube transcript url={url} video_id={video_id}")
        cache_key = self._youtube_cache_key(video_id)
        cached = await self.cache.get_json(cache_key)
        if cached:
            logger.debug(f"YouTube transcript cache hit video_id={video_id}")
            return SourceDocument(
                source_id=f"youtube:{video_id}",
                source_type="youtube",
                title=f"YouTube transcript {video_id}",
                url=url,
                content=str(cached.get("content") or ""),
                metadata={**cached.get("metadata", {}), "cache_hit": True},
            )

        try:
            result = await self.ai_stack.youtube_transcript(url)
            content = result.get("transcript", result.get("content", ""))
        except Exception as e:
            logger.warning(f"AiStackClient youtube_transcript failed for {url}: {e}")
            content = ""

        logger.debug(
            f"YouTube transcript fetched video_id={video_id} content_len={len(content)} cache_enabled={self.cache.enabled}"
        )
        doc = SourceDocument(
            source_id=f"youtube:{video_id}",
            source_type="youtube",
            title=f"YouTube transcript {video_id}",
            url=url,
            content=content,
            metadata={"video_id": video_id, "cache_hit": False, "backend": "ai_stack"},
        )

        if self.cache.enabled:
            await self.cache.set_json(
                cache_key,
                {"content": content, "metadata": {"video_id": video_id}},
            )
        return doc

    @staticmethod
    def _youtube_cache_key(video_id: str) -> str:
        return f"youtube:transcript:{video_id}"

    async def fetch_file_document(self, path: str) -> SourceDocument:
        from pathlib import Path

        file_path = Path(path)
        logger.info(f"Reading file document path={file_path}")
        doc = SourceDocument(
            source_id=f"file:{file_path.resolve()}",
            source_type="file",
            title=file_path.name,
            url=None,
            content=file_path.read_text(encoding="utf-8"),
            metadata={"path": str(file_path.resolve())},
        )
        logger.debug(f"File document read path={file_path} content_len={len(doc.content)}")
        return doc

    @staticmethod
    def _extract_youtube_id(url: str) -> str:
        parsed = urlparse(url)
        if parsed.hostname in {"youtu.be"}:
            return parsed.path.strip("/")
        query_video = parse_qs(parsed.query).get("v")
        if query_video:
            return query_video[0]
        match = re.search(r"/shorts/([^/?]+)", url)
        if match:
            return match.group(1)
        raise ValueError(f"Unsupported YouTube URL: {url}")
