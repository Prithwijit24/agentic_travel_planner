from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.ingestion.crawler import WebCrawler


class SourceConnectors:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.crawler = WebCrawler()

    async def fetch_wikivoyage(self, destination: str) -> SourceDocument:
        slug = destination.strip().replace(" ", "_")
        url = f"https://en.wikivoyage.org/wiki/{slug}"
        crawl_result = await self.crawler.fetch(url, backend="trafilatura")
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
        crawl_result = await self.crawler.fetch(url, backend=crawl_backend)
        final_title = title if title else crawl_result.title
        text = BeautifulSoup(crawl_result.content, "html.parser").get_text(" ", strip=True)
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
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        content = " ".join(item["text"] for item in transcript)
        return SourceDocument(
            source_id=f"youtube:{video_id}",
            source_type="youtube",
            title=f"YouTube transcript {video_id}",
            url=url,
            content=content,
            metadata={"video_id": video_id},
        )

    async def fetch_file_document(self, path: str) -> SourceDocument:
        from pathlib import Path

        file_path = Path(path)
        return SourceDocument(
            source_id=f"file:{file_path.resolve()}",
            source_type="file",
            title=file_path.name,
            url=None,
            content=file_path.read_text(encoding="utf-8"),
            metadata={"path": str(file_path.resolve())},
        )

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
