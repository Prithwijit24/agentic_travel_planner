import pytest

from agentic_tour_planner.cache.redis_cache import RedisCache
from agentic_tour_planner.config.settings import get_settings


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.ttls[key] = ttl


@pytest.mark.asyncio
async def test_redis_cache_round_trips_json(monkeypatch):
    monkeypatch.setenv("REDIS_CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_CACHE_NAMESPACE", "tests")
    monkeypatch.setenv("REDIS_CACHE_TTL_SECONDS", "42")
    get_settings.cache_clear()

    cache = RedisCache()
    fake_client = FakeRedisClient()
    cache._client = fake_client

    await cache.set_json("crawl:key", {"title": "Kyoto", "content": "temples"})
    value = await cache.get_json("crawl:key")

    assert value == {"title": "Kyoto", "content": "temples"}
    assert fake_client.ttls["tests:crawl:key"] == 42


@pytest.mark.asyncio
async def test_redis_cache_is_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("REDIS_CACHE_ENABLED", "false")
    get_settings.cache_clear()

    cache = RedisCache()

    await cache.set_json("ignored", {"value": "unused"})

    assert await cache.get_json("ignored") is None
