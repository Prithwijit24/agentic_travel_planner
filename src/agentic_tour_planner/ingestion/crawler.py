from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

import httpx
import trafilatura

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import CrawlBackend, ProxyRoutingStrategy


@dataclass
class CrawlResult:
    url: str
    title: str
    content: str
    metadata: dict[str, Any]


class ProxyRouter:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._rr_index = 0

    def route_for(self, url: str) -> str | None:
        urls = self.settings.outbound_proxy_urls
        if not urls:
            return None
        strategy: ProxyRoutingStrategy = self.settings.proxy_routing_strategy  # type: ignore[assignment]
        if strategy == "direct":
            return None
        if strategy == "round_robin":
            proxy = urls[self._rr_index % len(urls)]
            self._rr_index += 1
            return proxy
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(urls)
        return urls[index]


class WebCrawler:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.proxy_router = ProxyRouter()

    async def fetch(self, url: str, backend: CrawlBackend | None = None) -> CrawlResult:
        resolved_backend = backend or self.settings.web_crawl_backend
        if resolved_backend == "httpx":
            return await self._fetch_httpx(url)
        if resolved_backend == "crawl4ai":
            return await self._fetch_crawl4ai(url)
        return await self._fetch_trafilatura(url)

    async def _fetch_httpx(self, url: str) -> CrawlResult:
        proxy = self.proxy_router.route_for(url)
        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=True,
            proxy=proxy,
            headers={"User-Agent": self.settings.crawl_user_agents[0]},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
        return CrawlResult(
            url=url,
            title=url,
            content=response.text,
            metadata={"backend": "httpx", "proxy": proxy},
        )

    async def _fetch_trafilatura(self, url: str) -> CrawlResult:
        raw = await asyncio.to_thread(trafilatura.fetch_url, url)
        if not raw:
            raise ValueError(f"Failed to fetch {url}")
        extracted = trafilatura.extract(raw, with_metadata=True) or raw
        title = url
        return CrawlResult(
            url=url,
            title=title,
            content=extracted,
            metadata={"backend": "trafilatura"},
        )

    async def _fetch_crawl4ai(self, url: str) -> CrawlResult:
        try:
            from crawl4ai import AsyncWebCrawler
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("crawl4ai backend requested but package is not installed") from exc

        proxy = self.proxy_router.route_for(url)
        async with AsyncWebCrawler(verbose=False) as crawler:
            kwargs = {
                "url": url,
                "bypass_cache": True,
                "user_agent": self.settings.crawl_user_agents[0],
            }
            if proxy:
                kwargs["proxy"] = proxy
            result = await crawler.arun(**kwargs)
        content = getattr(result, "markdown", None) or getattr(result, "cleaned_html", None) or ""
        title = getattr(result, "title", None) or url
        return CrawlResult(
            url=url,
            title=title,
            content=content,
            metadata={"backend": "crawl4ai", "proxy": proxy},
        )
