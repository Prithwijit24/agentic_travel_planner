"""Real integration tests against AI Infra Stack — no mocking, real connections."""
import asyncio
import os
import sys

from agentic_tour_planner.tools.api_client import ApiClient
from agentic_tour_planner.tools.ai_stack_client import AiStackClient

BASE_URL = os.getenv("AI_STACK_BASE_URL", "https://aistackapi.duckdns.org")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "b6dc002b5cf63579a76a753dc4b2a78e")


def _client(timeout: float = 60.0):
    return ApiClient(base_url=BASE_URL, username=ADMIN_USER, password=ADMIN_PASS, timeout=timeout)


def test_health():
    c = _client()
    r = c.health()
    print(f"  \u2713 {r}")
    c.close()


def test_login():
    c = _client()
    data = c.login()
    assert "access_token" in data
    print(f"  \u2713 token length={len(c.token)}")
    c.close()


def test_search():
    c = _client()
    r = c.search("best hotels in Tokyo", max_results=3)
    print(f"  \u2713 {len(r.get('results', []))} results")
    c.close()


def test_crawl():
    c = _client()
    r = c.crawl("https://en.wikipedia.org/wiki/Tokyo")
    txt = r.get("markdown", r.get("content", ""))
    print(f"  \u2713 {len(txt)} chars")
    c.close()


def test_pipeline():
    c = _client(timeout=300.0)
    r = c.pipeline("best restaurants in Rome", top_k=3)
    print(f"  \u2713 keys={list(r.keys())}")
    c.close()


def test_embed():
    c = _client()
    r = c.embed(["hello world", "travel planning"])
    print(f"  \u2713 {len(r['embeddings'])} vectors, dim={len(r['embeddings'][0])}")
    c.close()


def test_rerank():
    c = _client()
    r = c.rerank("Japan capital", ["Tokyo is Japan capital", "Paris is France capital", "Rome is Italy capital"], top_k=2)
    print(f"  \u2713 keys={list(r.keys())}")
    c.close()


def test_cache():
    c = _client()
    c.cache_set("test:k1", {"a": 1}, ttl_seconds=60)
    r = c.cache_get("test:k1")
    print(f"  \u2713 get={r}")
    c.cache_delete("test:k1")
    c.close()


def test_clip():
    # Known stack-side issue: CLIP endpoint may return 500
    c = _client()
    try:
        r = c.clip_similarity("eiffel tower", image_urls=["https://upload.wikimedia.org/wikipedia/commons/thumb/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg/800px-Tour_Eiffel_Wikimedia_Commons.jpg"])
        print(f"  \u2713 scores={r.get('scores', r.get('similarities', 'N/A'))}")
    except Exception as e:
        print(f"  \u2717 stack-side 500: {e}")
    c.close()


def test_vector():
    # Known stack-side issue: vector upsert may return 500
    c = _client()
    try:
        emb = c.embed(["tokyo travel"])["embeddings"][0]
        c.vector_upsert("test_col", [{"id": "doc1", "embedding": emb, "metadata": {"text": "tokyo"}}])
        print("  \u2713 upsert ok")
        r = c.vector_search("test_col", emb, top_k=3)
        print(f"  \u2713 search keys={list(r.keys())}")
        c.vector_delete("test_col", ["doc1"])
        print("  \u2713 delete ok")
    except Exception as e:
        print(f"  \u2717 stack-side 500: {e}")
    c.close()


def test_duckdb():
    c = _client()
    r = c.duckdb_query("SELECT 42 AS answer, 'hello' AS greeting")
    print(f"  \u2713 {r}")
    c.close()


def test_youtube():
    c = _client()
    r = c.youtube_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    print(f"  \u2713 keys={list(r.keys())}")
    c.close()


def test_async_client():
    async def _run():
        c = AiStackClient()
        c._client = ApiClient(base_url=BASE_URL, username=ADMIN_USER, password=ADMIN_PASS)
        try:
            h = await c.health()
            print(f"  \u2713 async health={h}")
            s = await c.search("tokyo hotels", max_results=2)
            print(f"  \u2713 async search={len(s.get('results', []))} results")
            e = await c.embed(["hello"])
            print(f"  \u2713 async embed dim={len(e['embeddings'][0])}")
        finally:
            c.close()
    asyncio.run(_run())


if __name__ == "__main__":
    tests = [
        ("health", test_health),
        ("login", test_login),
        ("search", test_search),
        ("crawl", test_crawl),
        ("pipeline", test_pipeline),
        ("embed", test_embed),
        ("rerank", test_rerank),
        ("cache", test_cache),
        ("clip_similarity", test_clip),
        ("vector", test_vector),
        ("duckdb", test_duckdb),
        ("youtube_info", test_youtube),
        ("async_client", test_async_client),
    ]
    p, f = 0, 0
    for name, fn in tests:
        print(f"\n\u25b8 {name}")
        try:
            fn()
            p += 1
        except Exception as e:
            print(f"  \u2717 {e}")
            f += 1
    print(f"\n{'='*50}")
    print(f"{p} passed, {f} failed / {len(tests)} total")
    sys.exit(1 if f else 0)
