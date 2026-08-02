"""Unit tests for the async AiStackClient wrapper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from agentic_tour_planner.tools.ai_stack_client import AiStackClient


def _mock_api_client(**overrides):
    """Create a mock ApiClient with sensible defaults."""
    mock = MagicMock()
    mock.base_url = "http://localhost:8000"
    mock.health.return_value = {"status": "healthy"}
    mock.search.return_value = {"results": []}
    mock.crawl.return_value = {"markdown": "# content"}
    mock.pipeline.return_value = {"results": []}
    mock.embed.return_value = {"embeddings": [[0.1, 0.2]]}
    mock.clip_similarity.return_value = {"scores": [0.9]}
    mock.clip_text_embedding.return_value = {"embeddings": [[0.1]]}
    mock.clip_image_embedding.return_value = {"embeddings": [[0.1]]}
    mock.images.return_value = {"images": [{"url": "http://img.jpg", "clip_score": 0.9}]}
    mock.news.return_value = {
        "articles": [{"title": "Test News", "url": "http://news.example.com", "source": "test", "snippet": "..."}]
    }
    mock.rerank.return_value = {"ranked": []}
    mock.cache_get.return_value = {"value": {"key": "val"}}
    mock.cache_set.return_value = {"ok": True}
    mock.cache_delete.return_value = {"ok": True}
    mock.vector_upsert.return_value = {"count": 1}
    mock.vector_search.return_value = {"results": []}
    mock.vector_delete.return_value = {"ok": True}
    mock.graph_query.return_value = {"records": []}
    mock.graph_add_node.return_value = {"ok": True}
    mock.graph_add_edge.return_value = {"ok": True}
    mock.youtube_info.return_value = {"title": "Test"}
    mock.youtube_transcript.return_value = {"transcript": "Hello"}
    mock.youtube_thumbnail.return_value = {"url": "thumb.jpg"}
    mock.youtube_download_audio.return_value = {"job_id": "j1"}
    mock.youtube_download_video.return_value = {"job_id": "j2"}
    mock.youtube_job_status.return_value = {"status": "done"}
    mock.duckdb_query.return_value = {"rows": []}
    mock.duckdb_insert.return_value = {"ok": True}
    mock.duckdb_tables.return_value = {"tables": []}
    mock.storage_list.return_value = {"files": []}
    mock.storage_upload.return_value = {"ok": True}
    mock.storage_download.return_value = MagicMock()
    mock.storage_delete.return_value = {"ok": True}
    mock.browse.return_value = {"content": "page content"}
    mock.close.return_value = None
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


@pytest.fixture
def client_with_mock():
    """Create an AiStackClient with a mocked ApiClient."""
    mock_api = _mock_api_client()
    with patch("agentic_tour_planner.tools.ai_stack_client.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            ai_stack_base_url="http://localhost:8000",
            ai_stack_admin_user="admin",
            ai_stack_admin_pass="pass",
            ai_stack_token="",
            ai_stack_timeout_seconds=1000.0,
        )
        c = AiStackClient()
    c._client = mock_api
    return c, mock_api


# ── init ─────────────────────────────────────────────────────────────


class TestAiStackClientInit:
    def test_timeout_passed_through(self):
        with patch("agentic_tour_planner.tools.ai_stack_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                ai_stack_base_url="http://localhost:8000",
                ai_stack_admin_user="admin",
                ai_stack_admin_pass="pass",
                ai_stack_token="",
                ai_stack_timeout_seconds=1000.0,
            )
            c = AiStackClient()
        assert c._client._client.timeout == httpx.Timeout(1000.0)

    def test_timeout_defaults_to_1000_when_unset(self):
        with patch("agentic_tour_planner.tools.ai_stack_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                ai_stack_base_url="http://localhost:8000",
                ai_stack_admin_user="admin",
                ai_stack_admin_pass="pass",
                ai_stack_token="",
                ai_stack_timeout_seconds=None,
            )
            c = AiStackClient()
        assert c._client._client.timeout == httpx.Timeout(1000.0)


# ── lifecycle ────────────────────────────────────────────────────────


class TestAiStackClientLifecycle:
    def test_close(self, client_with_mock):
        c, mock_api = client_with_mock
        c.close()
        mock_api.close.assert_called_once()

    def test_context_manager(self, client_with_mock):
        c, mock_api = client_with_mock
        with c as client:
            assert client is c
        mock_api.close.assert_called_once()


# ── core ─────────────────────────────────────────────────────────────


class TestAiStackClientCore:
    @pytest.mark.asyncio
    async def test_health(self, client_with_mock):
        c, _mock_api = client_with_mock
        result = await c.health()
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_search(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.search("tokyo", categories="images", max_results=5)
        mock_api.search.assert_called_once_with(
            "tokyo",
            categories="images",
            language="en",
            max_results=5,
        )

    @pytest.mark.asyncio
    async def test_browse(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.browse("https://example.com", action="screenshot")
        mock_api.browse.assert_called_once()

    @pytest.mark.asyncio
    async def test_crawl(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.crawl("https://example.com")
        mock_api.crawl.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_pipeline(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.pipeline("best hotels", top_k=3, crawl_limit=5)
        mock_api.pipeline.assert_called_once_with(
            "best hotels",
            top_k=3,
            crawl_limit=5,
            max_search_results=15,
        )

    @pytest.mark.asyncio
    async def test_stream_pipeline(self, client_with_mock):
        c, mock_api = client_with_mock
        mock_api.stream_pipeline.return_value = iter(
            [
                {"event": "search", "data": {"query": "test"}},
                {"event": "result", "data": {"url": "https://example.com"}},
            ]
        )
        result = await c.stream_pipeline("test query", top_k=5)
        mock_api.stream_pipeline.assert_called_once_with("test query", top_k=5)
        events = list(result)
        assert len(events) == 2
        assert events[0]["event"] == "search"
        assert events[1]["event"] == "result"

    @pytest.mark.asyncio
    async def test_embed(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.embed(["hello", "world"])
        mock_api.embed.assert_called_once_with(["hello", "world"])

    @pytest.mark.asyncio
    async def test_rerank(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.rerank("query", ["doc1", "doc2"], top_k=2)
        mock_api.rerank.assert_called_once_with("query", ["doc1", "doc2"], top_k=2)


# ── CLIP ─────────────────────────────────────────────────────────────


class TestAiStackClientCLIP:
    @pytest.mark.asyncio
    async def test_clip_text_embedding(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.clip_text_embedding(["eiffel tower"])
        mock_api.clip_text_embedding.assert_called_once_with(["eiffel tower"])

    @pytest.mark.asyncio
    async def test_clip_image_embedding_urls(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.clip_image_embedding(image_urls=["http://img.jpg"])
        mock_api.clip_image_embedding.assert_called_once_with(
            image_urls=["http://img.jpg"],
            images_base64=None,
        )

    @pytest.mark.asyncio
    async def test_clip_image_embedding_base64(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.clip_image_embedding(images_base64=["abc123"])
        mock_api.clip_image_embedding.assert_called_once_with(
            image_urls=None,
            images_base64=["abc123"],
        )

    @pytest.mark.asyncio
    async def test_clip_similarity_urls(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.clip_similarity("query", image_urls=["http://img.jpg"])
        mock_api.clip_similarity.assert_called_once_with(
            "query",
            image_urls=["http://img.jpg"],
            images_base64=None,
        )

    @pytest.mark.asyncio
    async def test_clip_similarity_base64(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.clip_similarity("query", images_base64=["abc123"])
        mock_api.clip_similarity.assert_called_once_with(
            "query",
            image_urls=None,
            images_base64=["abc123"],
        )

    @pytest.mark.asyncio
    async def test_images(self, client_with_mock):
        c, mock_api = client_with_mock
        mock_api.images.return_value = {"results": [{"url": "http://img.jpg", "clip_score": 0.9}]}
        await c.images("eiffel tower", max_results=5, use_clip=True)
        mock_api.images.assert_called_once_with(
            "eiffel tower",
            max_results=5,
            use_clip=True,
        )

    @pytest.mark.asyncio
    async def test_images_defaults(self, client_with_mock):
        c, mock_api = client_with_mock
        mock_api.images.return_value = {"results": []}
        await c.images("query")
        mock_api.images.assert_called_once_with(
            "query",
            max_results=10,
            use_clip=True,
        )

    @pytest.mark.asyncio
    async def test_news(self, client_with_mock):
        c, mock_api = client_with_mock
        mock_api.news.return_value = {"articles": [{"title": "Test News"}]}
        await c.news("tokyo", max_results=5, timelimit="m")
        mock_api.news.assert_called_once_with(
            "tokyo",
            max_results=5,
            timelimit="m",
        )


# ── cache ────────────────────────────────────────────────────────────


class TestAiStackClientCache:
    @pytest.mark.asyncio
    async def test_cache_set(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.cache_set("key1", {"val": 1}, ttl_seconds=300)
        mock_api.cache_set.assert_called_once_with("key1", {"val": 1}, ttl_seconds=300)

    @pytest.mark.asyncio
    async def test_cache_get(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.cache_get("key1")
        mock_api.cache_get.assert_called_once_with("key1")

    @pytest.mark.asyncio
    async def test_cache_delete(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.cache_delete("key1")
        mock_api.cache_delete.assert_called_once_with("key1")


# ── vector ───────────────────────────────────────────────────────────


class TestAiStackClientVector:
    @pytest.mark.asyncio
    async def test_vector_upsert(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.vector_upsert("col", [{"id": "1"}])
        mock_api.vector_upsert.assert_called_once_with("col", [{"id": "1"}])

    @pytest.mark.asyncio
    async def test_vector_search(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.vector_search("col", [0.1, 0.2], top_k=10)
        mock_api.vector_search.assert_called_once_with("col", [0.1, 0.2], top_k=10)

    @pytest.mark.asyncio
    async def test_vector_delete(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.vector_delete("col", ["id1", "id2"])
        mock_api.vector_delete.assert_called_once_with("col", ["id1", "id2"])


# ── graph ────────────────────────────────────────────────────────────


class TestAiStackClientGraph:
    @pytest.mark.asyncio
    async def test_graph_query(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.graph_query("MATCH (n) RETURN n", {"param": 1})
        mock_api.graph_query.assert_called_once_with("MATCH (n) RETURN n", parameters={"param": 1})

    @pytest.mark.asyncio
    async def test_graph_add_node(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.graph_add_node("Place", {"name": "Eiffel"}, merge_key="name")
        mock_api.graph_add_node.assert_called_once()

    @pytest.mark.asyncio
    async def test_graph_add_edge(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.graph_add_edge("A", "id", "1", "B", "id", "2", "LINKS_TO")
        mock_api.graph_add_edge.assert_called_once()


# ── YouTube ──────────────────────────────────────────────────────────


class TestAiStackClientYouTube:
    @pytest.mark.asyncio
    async def test_youtube_info(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.youtube_info("https://youtube.com/watch?v=abc")
        mock_api.youtube_info.assert_called_once_with("https://youtube.com/watch?v=abc")

    @pytest.mark.asyncio
    async def test_youtube_transcript(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.youtube_transcript("https://youtube.com/watch?v=abc", language="ja")
        mock_api.youtube_transcript.assert_called_once_with(
            "https://youtube.com/watch?v=abc",
            language="ja",
        )

    @pytest.mark.asyncio
    async def test_youtube_thumbnail(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.youtube_thumbnail("https://youtube.com/watch?v=abc")
        mock_api.youtube_thumbnail.assert_called_once()

    @pytest.mark.asyncio
    async def test_youtube_download_audio(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.youtube_download_audio("https://youtube.com/watch?v=abc", quality="best")
        mock_api.youtube_download_audio.assert_called_once()

    @pytest.mark.asyncio
    async def test_youtube_download_video(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.youtube_download_video("https://youtube.com/watch?v=abc")
        mock_api.youtube_download_video.assert_called_once()

    @pytest.mark.asyncio
    async def test_youtube_job_status(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.youtube_job_status("job-123")
        mock_api.youtube_job_status.assert_called_once_with("job-123")


# ── DuckDB ───────────────────────────────────────────────────────────


class TestAiStackClientDuckDB:
    @pytest.mark.asyncio
    async def test_duckdb_query(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.duckdb_query("SELECT 1", params=[1])
        mock_api.duckdb_query.assert_called_once_with("SELECT 1", params=[1])

    @pytest.mark.asyncio
    async def test_duckdb_insert(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.duckdb_insert("t", ["a"], [{"a": 1}])
        mock_api.duckdb_insert.assert_called_once_with("t", ["a"], [{"a": 1}])

    @pytest.mark.asyncio
    async def test_duckdb_tables(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.duckdb_tables()
        mock_api.duckdb_tables.assert_called_once()


# ── storage ──────────────────────────────────────────────────────────


class TestAiStackClientStorage:
    @pytest.mark.asyncio
    async def test_storage_list(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.storage_list("prefix/", bucket="my-bucket")
        mock_api.storage_list.assert_called_once_with("prefix/", bucket="my-bucket")

    @pytest.mark.asyncio
    async def test_storage_upload(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.storage_upload("key1", file_bytes=b"data", filename="test.bin")
        mock_api.storage_upload.assert_called_once()

    @pytest.mark.asyncio
    async def test_storage_download(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.storage_download("bucket", "key1")
        mock_api.storage_download.assert_called_once_with("bucket", "key1")

    @pytest.mark.asyncio
    async def test_storage_delete(self, client_with_mock):
        c, mock_api = client_with_mock
        await c.storage_delete(["key1", "key2"], bucket="b")
        mock_api.storage_delete.assert_called_once_with(["key1", "key2"], bucket="b")
