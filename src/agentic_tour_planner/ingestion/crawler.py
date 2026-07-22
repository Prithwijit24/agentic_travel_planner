from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

import trafilatura

from agentic_tour_planner.cache import RedisCache
from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import ProxyRoutingStrategy
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CrawlResult:
    url: str
    title: str
    content: str
    metadata: dict[str, Any]


class WebCrawler:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._proxy_rr_index = 0
        self.cache = RedisCache()
        logger.debug("Initialized WebCrawler")

    def _route_proxy(self, url: str) -> str | None:
        urls = self.settings.outbound_proxy_urls
        if not urls:
            return None
        strategy: ProxyRoutingStrategy = self.settings.proxy_routing_strategy  # type: ignore[assignment]
        if strategy == "direct":
            return None
        if strategy == "round_robin":
            proxy = urls[self._proxy_rr_index % len(urls)]
            self._proxy_rr_index += 1
            logger.debug(f"Routed proxy (round_robin) url={url} has_proxy={proxy is not None}")
            return proxy
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(urls)
        logger.debug(f"Routed proxy (hash) url={url} has_proxy={True}")
        return urls[index]

    async def fetch(self, url: str, backend: str | None = None) -> CrawlResult:
        resolved_backend = backend or self.settings.web_crawl_backend
        logger.info(f"Fetching url={url} backend={resolved_backend}")
        cache_key = self._cache_key(url, resolved_backend)
        cached = await self.cache.get_json(cache_key)
        if cached:
            logger.debug(f"Cache hit url={url} backend={resolved_backend}")
            return CrawlResult(
                url=str(cached.get("url") or url),
                title=str(cached.get("title") or url),
                content=str(cached.get("content") or ""),
                metadata={**dict(cached.get("metadata") or {}), "cache_hit": True},
            )

        if resolved_backend == "scrapling":
            result = await self._fetch_scrapling(url)
        else:
            result = await self._fetch_trafilatura(url)

        logger.debug(
            f"Fetched url={url} backend={resolved_backend} title={result.title!r} content_len={len(result.content)}"
        )
        await self.cache.set_json(
            cache_key,
            {
                "url": result.url,
                "title": result.title,
                "content": result.content,
                "metadata": result.metadata,
            },
        )
        if self.cache.enabled:
            result.metadata = {**result.metadata, "cache_hit": False}
        return result

    @staticmethod
    def _cache_key(url: str, backend: str) -> str:
        digest = hashlib.sha256(f"{backend}:{url}".encode()).hexdigest()
        return f"crawl:{backend}:{digest}"

    async def _fetch_trafilatura(self, url: str) -> CrawlResult:
        logger.debug(f"Trafilatura fetch start url={url}")
        raw = await asyncio.to_thread(trafilatura.fetch_url, url)
        if not raw:
            raise ValueError(f"Failed to fetch {url}")
        extracted = trafilatura.extract(raw, with_metadata=True) or raw
        title = url
        logger.debug(f"Trafilatura fetch done url={url} raw_len={len(raw)} extracted_len={len(extracted)}")
        return CrawlResult(
            url=url,
            title=title,
            content=extracted,
            metadata={"backend": "trafilatura"},
        )

    async def _fetch_scrapling(self, url: str) -> CrawlResult:
        try:
            from scrapling.fetchers import AsyncFetcher
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("scrapling backend requested but package is not installed") from exc

        proxy = self._route_proxy(url)
        logger.debug(f"Scrapling fetch start url={url} has_proxy={proxy is not None}")
        page = await AsyncFetcher.get(
            url,
            follow_redirects=True,
            timeout=self.settings.request_timeout_seconds,
            proxy=proxy,
            headers={"User-Agent": self.settings.crawl_user_agents[0]},
        )
        status = getattr(page, "status", None)
        if status is not None and status >= 400:
            reason = getattr(page, "reason", "")
            raise ValueError(f"Scrapling failed to fetch {url}: HTTP {status} {reason}".strip())
        content = page.get_all_text(ignore_tags=("script", "style")) or getattr(page, "html_content", "") or ""
        title = page.css("title::text").get() or url
        logger.debug(f"Scrapling fetch done url={url} status={status} content_len={len(content)}")
        return CrawlResult(
            url=url,
            title=str(title or url),
            content=str(content),
            metadata={"backend": "scrapling", "proxy": proxy, "status": status},
        )
