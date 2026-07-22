import sys
from types import ModuleType, SimpleNamespace

import pytest

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.ingestion.crawler import CrawlResult, WebCrawler


class FakeSelector:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class FakePage:
    status = 200
    reason = "OK"
    html_content = "<html><title>Kyoto Guide</title><body>Kyoto temples</body></html>"

    def get_all_text(self, ignore_tags=()) -> str:
        return "Kyoto temples"

    def css(self, selector: str) -> FakeSelector:
        if selector == "title::text":
            return FakeSelector("Kyoto Guide")
        return FakeSelector("")


@pytest.mark.asyncio
async def test_scrapling_backend_fetches_page(monkeypatch):
    class FakeAsyncFetcher:
        @classmethod
        async def get(cls, url: str, **kwargs):
            assert url == "https://example.com/kyoto"
            assert kwargs["follow_redirects"] is True
            return FakePage()

    fetchers_module = ModuleType("scrapling.fetchers")
    fetchers_module.AsyncFetcher = FakeAsyncFetcher
    scrapling_module = ModuleType("scrapling")
    monkeypatch.setitem(sys.modules, "scrapling", scrapling_module)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fetchers_module)

    get_settings.cache_clear()
    result = await WebCrawler().fetch("https://example.com/kyoto", backend="scrapling")

    assert result.title == "Kyoto Guide"
    assert result.content == "Kyoto temples"
    assert result.metadata["backend"] == "scrapling"


@pytest.mark.asyncio
async def test_crawler_uses_redis_cache_when_enabled(monkeypatch):
    monkeypatch.setenv("REDIS_CACHE_ENABLED", "true")
    get_settings.cache_clear()

    crawler = WebCrawler()
    cached_payload = {
        "url": "https://example.com/cache",
        "title": "Cached",
        "content": "cached content",
        "metadata": {"backend": "scrapling"},
    }
    crawler.cache = SimpleNamespace(
        enabled=True,
        get_json=lambda key: _async_value(cached_payload),
        set_json=lambda key, value: _async_value(None),
    )

    async def should_not_fetch(url: str) -> CrawlResult:
        raise AssertionError("cache hit should not call backend fetch")

    crawler._fetch_scrapling = should_not_fetch

    result = await crawler.fetch("https://example.com/cache", backend="scrapling")

    assert result.title == "Cached"
    assert result.content == "cached content"
    assert result.metadata["cache_hit"] is True


async def _async_value(value):
    return value
