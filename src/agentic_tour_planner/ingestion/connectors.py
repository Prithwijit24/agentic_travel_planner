from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi

from agentic_tour_planner.cache import RedisCache
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.ingestion.crawler import WebCrawler
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class SourceConnectors:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.crawler = WebCrawler()
        self.cache = RedisCache()
        logger.debug("Initialized SourceConnectors")

    async def fetch_wikivoyage(self, destination: str) -> SourceDocument:
        slug = destination.strip().replace(" ", "_")
        url = f"https://en.wikivoyage.org/wiki/{slug}"
        logger.info(f"Fetching Wikivoyage page for destination={destination!r} url={url}")
        crawl_result = await self.crawler.fetch(url, backend="trafilatura")
        logger.debug(f"Wikivoyage crawl complete title={crawl_result.title!r} content_len={len(crawl_result.content)}")
        return SourceDocument(
            source_id=f"wikivoyage:{slug.lower()}",
            source_type="wikivoyage",
            title=f"{destination} travel guide",
            url=url,
            content=crawl_result.content,
            metadata={"destination": destination, **crawl_result.metadata},
        )

    async def fetch_web_document(
        self,
        url: str,
        source_id: str,
        title: str,
        source_type: str = "web",
        crawl_backend: str | None = None,
    ) -> SourceDocument:
        logger.info(
            f"Fetching web document url={url} source_id={source_id} source_type={source_type} crawl_backend={crawl_backend}"
        )
        crawl_result = await self.crawler.fetch(url, backend=crawl_backend)
        final_title = title if title else crawl_result.title
        text = BeautifulSoup(crawl_result.content, "html.parser").get_text(" ", strip=True)
        logger.debug(f"Web document fetched title={final_title!r} text_len={len(text or crawl_result.content)}")
        return SourceDocument(
            source_id=source_id,
            source_type=source_type,  # type: ignore[arg-type]
            title=final_title,
            url=url,
            content=text or crawl_result.content,
            metadata=crawl_result.metadata,
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

        transcript = YouTubeTranscriptApi().fetch(video_id)
        content = " ".join(snippet.text for snippet in transcript)
        logger.debug(
            f"YouTube transcript fetched video_id={video_id} content_len={len(content)} cache_enabled={self.cache.enabled}"
        )
        doc = SourceDocument(
            source_id=f"youtube:{video_id}",
            source_type="youtube",
            title=f"YouTube transcript {video_id}",
            url=url,
            content=content,
            metadata={"video_id": video_id, "cache_hit": False},
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
