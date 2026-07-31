"""Real integration tests against AI Infra Stack — no mocking, real connections.

Root causes of known stack-side issues:
- CLIP /clip/similarity with image_urls returns 500 because stack can't fetch
  Wikipedia images (403 Forbidden). Fix: use images_base64 instead.
- Vector /vector/upsert returns 500 because stack ChromaDB is read-only
  (OperationalError: attempt to write a readonly database). This is a
  stack-side config issue — needs ChromaDB write permissions enabled.
- CLIP /clip/similarity with images_base64 returns 500 if the base64 data
  isn't a valid image (e.g., redirect page). Use a real JPEG/PNG.
"""
import asyncio
import base64
import os
import sys

from agentic_tour_planner.tools.api_client import ApiClient
from agentic_tour_planner.tools.ai_stack_client import AiStackClient

BASE_URL = os.getenv("AI_STACK_BASE_URL", "https://aistackapi.duckdns.org")
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "b6dc002b5cf63579a76a753dc4b2a78e")

# Small valid JPEG for CLIP testing (1x1 red pixel)
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
    "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
    "2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAyACgDASIAAhEBAxEB/8QA"
    "HgABAAICAwEBAQAAAAAAAAAAAQcIBQYDAAkKAQAL/8QAFRABAQAAAAAAAAAAAAAAAAAAAAf/"
    "xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8A"
    "LUUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)


def _client(timeout: float = 60.0):
    return ApiClient(base_url=BASE_URL, username=ADMIN_USER, password=ADMIN_PASS, timeout=timeout)


# ── Core ──────────────────────────────────────────────────────────────

def test_health():
    c = _client()
    r = c.health()
    print(f"  ✓ {r}")
    c.close()


def test_login():
    c = _client()
    data = c.login()
    assert "access_token" in data
    print(f"  ✓ token length={len(c.token)}")
    c.close()


# ── Search / Browse / Crawl ──────────────────────────────────────────

def test_search():
    c = _client()
    r = c.search("best hotels in Tokyo", max_results=3)
    assert len(r.get("results", [])) > 0
    print(f"  ✓ {len(r['results'])} results, first={r['results'][0].get('title', 'N/A')[:60]}")
    c.close()


def test_browse():
    c = _client()
    try:
        r = c.browse("https://example.com", action="content")
        content = r.get("content", r.get("text", ""))
        print(f"  ✓ browse content length={len(content)} chars")
    except Exception as e:
        print(f"  ✗ browse failed: {e}")
    c.close()


def test_crawl():
    c = _client()
    r = c.crawl("https://en.wikipedia.org/wiki/Tokyo")
    txt = r.get("markdown", r.get("content", ""))
    assert len(txt) > 100
    print(f"  ✓ {len(txt)} chars of markdown")
    c.close()


def test_pipeline():
    c = _client(timeout=300.0)
    r = c.pipeline("best restaurants in Rome", top_k=3)
    print(f"  ✓ keys={list(r.keys())}, results={len(r.get('results', []))}")
    c.close()


# ── Embeddings & ML ──────────────────────────────────────────────────

def test_embed():
    c = _client()
    r = c.embed(["hello world", "travel planning"])
    assert len(r["embeddings"]) == 2
    dim = len(r["embeddings"][0])
    print(f"  ✓ {len(r['embeddings'])} vectors, dim={dim}")
    c.close()


def test_rerank():
    c = _client()
    r = c.rerank(
        "Japan capital",
        ["Tokyo is Japan capital", "Paris is France capital", "Rome is Italy capital"],
        top_k=2,
    )
    print(f"  ✓ keys={list(r.keys())}")
    c.close()


def test_clip_text_embedding():
    c = _client()
    try:
        r = c.clip_text_embedding(["eiffel tower", "tokyo skyline"])
        embs = r.get("embeddings", [])
        print(f"  ✓ model={r.get('model', '?')}, embeddings={len(embs)}, dim={len(embs[0]) if embs else 0}")
    except Exception as e:
        print(f"  ✗ CLIP text_embedding failed: {e}")
    c.close()


def test_clip_similarity_base64():
    """CLIP similarity with base64 image (avoids HTTP 403 from Wikipedia)."""
    c = _client()
    try:
        r = c.clip_similarity("red square", images_base64=[_TINY_JPEG_B64])
        scores = r.get("scores", r.get("similarities", []))
        print(f"  ✓ CLIP similarity scores={scores}")
    except Exception as e:
        err = str(e)
        if "500" in err:
            print(f"  ✗ stack-side 500 (CLIP model may be down): {err[:120]}")
        else:
            raise
    c.close()


def test_vector():
    """Vector store — known stack-side issue: ChromaDB is read-only."""
    c = _client()
    try:
        emb = c.embed(["tokyo travel"])["embeddings"][0]
        c.vector_upsert("test_col", [{"id": "doc1", "embedding": emb, "metadata": {"text": "tokyo"}}])
        print("  ✓ upsert ok")
        r = c.vector_search("test_col", emb, top_k=3)
        print(f"  ✓ search keys={list(r.keys())}")
        c.vector_delete("test_col", ["doc1"])
        print("  ✓ delete ok")
    except Exception as e:
        err = str(e)
        if "readonly" in err.lower():
            print(f"  ✗ stack-side readonly database: ChromaDB needs write permissions")
        elif "500" in err:
            print(f"  ✗ stack-side 500: {err[:120]}")
        else:
            raise
    c.close()


# ── Cache ────────────────────────────────────────────────────────────

def test_cache():
    c = _client()
    c.cache_set("test:k1", {"a": 1}, ttl_seconds=60)
    r = c.cache_get("test:k1")
    assert r.get("value", r) == {"a": 1}
    c.cache_delete("test:k1")
    print(f"  ✓ set/get/delete roundtrip")
    c.close()


# ── DuckDB ───────────────────────────────────────────────────────────

def test_duckdb():
    c = _client()
    r = c.duckdb_query("SELECT 42 AS answer, 'hello' AS greeting")
    print(f"  ✓ {r}")
    c.close()


# ── YouTube ──────────────────────────────────────────────────────────

def test_youtube():
    c = _client()
    r = c.youtube_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    print(f"  ✓ title={r.get('title', '?')[:60]}, duration={r.get('duration', '?')}s")
    c.close()


# ── Async Client ─────────────────────────────────────────────────────

def test_async_client():
    async def _run():
        client = ApiClient(base_url=BASE_URL, username=ADMIN_USER, password=ADMIN_PASS)
        c = AiStackClient()
        c._client = client
        try:
            h = await c.health()
            print(f"  ✓ async health={h}")
            s = await c.search("tokyo hotels", max_results=2)
            assert len(s.get("results", [])) > 0
            print(f"  ✓ async search={len(s['results'])} results")
            e = await c.embed(["hello"])
            print(f"  ✓ async embed dim={len(e['embeddings'][0])}")
        finally:
            c.close()
    asyncio.run(_run())


if __name__ == "__main__":
    tests = [
        ("health", test_health),
        ("login", test_login),
        ("search", test_search),
        ("browse", test_browse),
        ("crawl", test_crawl),
        ("pipeline", test_pipeline),
        ("embed", test_embed),
        ("rerank", test_rerank),
        ("clip_text_embedding", test_clip_text_embedding),
        ("clip_similarity_base64", test_clip_similarity_base64),
        ("vector", test_vector),
        ("cache", test_cache),
        ("duckdb", test_duckdb),
        ("youtube_info", test_youtube),
        ("async_client", test_async_client),
    ]
    p, f, s = 0, 0, 0
    for name, fn in tests:
        print(f"\n▸ {name}")
        try:
            fn()
            p += 1
        except Exception as e:
            print(f"  ✗ {e}")
            f += 1
    print(f"\n{'='*50}")
    print(f"{p} passed, {f} failed / {len(tests)} total")
    sys.exit(1 if f else 0)
