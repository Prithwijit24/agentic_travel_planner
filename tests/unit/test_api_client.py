"""Unit tests for the synchronous ApiClient wrapper."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, mock_open

import httpx
import pytest

from agentic_tour_planner.tools.api_client import ApiClient, DEFAULT_BASE_URL, DEFAULT_ADMIN_USER


# ── helpers ──────────────────────────────────────────────────────────

def _mock_response(json_data=None, status_code=200, text=""):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or json.dumps(json_data or {})
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code} Error",
            request=MagicMock(),
            response=resp,
        )
    return resp


def _make_client(**kwargs) -> ApiClient:
    """Create an ApiClient with a mock httpx.Client."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.base_url = httpx.URL(kwargs.pop("base_url", DEFAULT_BASE_URL))
    kwargs["client"] = mock_client
    client = ApiClient(**kwargs)
    client._client = mock_client
    return client, mock_client


# ── initialization ───────────────────────────────────────────────────

class TestApiClientInit:
    def test_default_base_url(self):
        client = ApiClient.__new__(ApiClient)
        with patch("agentic_tour_planner.tools.api_client.os.getenv", return_value=None):
            client.__init__()
        assert client.base_url == DEFAULT_BASE_URL

    def test_custom_base_url(self):
        client, mock_client = _make_client(base_url="http://custom:9000")
        assert client.base_url == "http://custom:9000"

    def test_trailing_slash_stripped(self):
        client, mock_client = _make_client(base_url="http://custom:9000/")
        assert client.base_url == "http://custom:9000"

    def test_token_precedence(self):
        client, mock_client = _make_client(token="my-token")
        assert client.token == "my-token"

    def test_username_defaults(self):
        client, mock_client = _make_client()
        assert client.username == DEFAULT_ADMIN_USER

    def test_custom_credentials(self):
        client, mock_client = _make_client(username="user", password="pass")
        assert client.username == "user"
        assert client.password == "pass"


# ── lifecycle ────────────────────────────────────────────────────────

class TestApiClientLifecycle:
    def test_close(self):
        client, mock_client = _make_client()
        client.close()
        mock_client.close.assert_called_once()

    def test_context_manager(self):
        client, mock_client = _make_client()
        with client as c:
            assert c is client
        mock_client.close.assert_called_once()


# ── endpoint index ───────────────────────────────────────────────────

class TestEndpointIndex:
    def test_all_expected_endpoints_exist(self):
        expected = [
            "login", "search", "crawl", "pipeline", "embed",
            "clip_similarity", "cache_get", "vector_upsert",
            "youtube_info", "duckdb_query", "storage_list",
        ]
        for name in expected:
            assert name in ApiClient.ENDPOINT_INDEX

    def test_endpoint_format(self):
        for name, (method, path) in ApiClient.ENDPOINT_INDEX.items():
            assert method in ("GET", "POST", "PUT", "DELETE", "PATCH")
            assert path.startswith("/")


# ── auth ─────────────────────────────────────────────────────────────

class TestApiClientAuth:
    def test_login(self):
        client, mock_client = _make_client()
        resp = _mock_response({"access_token": "tok123"})
        mock_client.post.return_value = resp
        data = client.login()
        assert client.token == "tok123"
        assert data["access_token"] == "tok123"

    def test_ensure_auth_skips_when_token_set(self):
        client, mock_client = _make_client(token="existing")
        client.ensure_auth()
        mock_client.request.assert_not_called()

    def test_ensure_auth_calls_login_when_no_token(self):
        client, mock_client = _make_client()
        resp = _mock_response({"access_token": "new-token"})
        mock_client.post.return_value = resp
        client.ensure_auth()
        assert client.token == "new-token"

    def test_headers_with_token(self):
        client, _ = _make_client(token="tok123")
        assert client._headers() == {"Authorization": "Bearer tok123"}

    def test_headers_without_token(self):
        client, _ = _make_client()
        client.token = ""
        assert client._headers() == {}


# ── core endpoints ───────────────────────────────────────────────────

class TestApiClientCore:
    def test_root(self):
        client, mock_client = _make_client()
        mock_client.request.return_value = _mock_response({"status": "ok"})
        result = client.root()
        assert result["status"] == "ok"
        # _request calls _client.request(method, path, headers=...)
        call_args = mock_client.request.call_args
        assert call_args[0][0] == "GET"
        assert call_args[0][1] == "/"
        assert "Authorization" not in call_args[1]["headers"]

    def test_health(self):
        client, mock_client = _make_client()
        mock_client.request.return_value = _mock_response({"healthy": True})
        result = client.health()
        assert result["healthy"] is True

    def test_search(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"results": []})
        result = client.search("test query", categories="images")
        assert "results" in result
        call_args = mock_client.request.call_args
        assert call_args[0] == ("POST", "/search")
        body = call_args[1]["json"]
        assert body["query"] == "test query"
        assert body["categories"] == "images"

    def test_crawl(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"markdown": "# Hello"})
        result = client.crawl("https://example.com")
        assert result["markdown"] == "# Hello"

    def test_pipeline(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"results": []})
        result = client.pipeline("best hotels in sikkim", top_k=5)
        call_args = mock_client.request.call_args
        body = call_args[1]["json"]
        assert body["query"] == "best hotels in sikkim"
        assert body["top_k"] == 5

    def test_embed(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"embeddings": [[0.1]]})
        result = client.embed(["hello world"])
        assert "embeddings" in result

    def test_clip_similarity(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"scores": [0.9]})
        result = client.clip_similarity("eiffel tower", image_urls=["http://img.jpg"])
        assert result["scores"] == [0.9]

    def test_rerank(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"ranked": []})
        result = client.rerank("query", ["doc1", "doc2"], top_k=1)
        body = mock_client.request.call_args[1]["json"]
        assert body["top_k"] == 1

    def test_cache_set_get_delete(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"ok": True})
        client.cache_set("key1", {"val": 1}, ttl_seconds=300)
        client.cache_get("key1")
        client.cache_delete("key1")
        assert mock_client.request.call_count == 3

    def test_vector_operations(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"count": 1})
        client.vector_upsert("col", [{"id": "1", "embedding": [0.1]}])
        client.vector_search("col", [0.1], top_k=5)
        client.vector_delete("col", ["1"])
        assert mock_client.request.call_count == 3

    def test_graph_operations(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"ok": True})
        client.graph_query("MATCH (n) RETURN n")
        client.graph_add_node("Place", {"name": "Eiffel"})
        client.graph_add_edge("A", "id", "1", "B", "id", "2", "LINKS_TO")
        assert mock_client.request.call_count == 3

    def test_duckdb_operations(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"rows": []})
        client.duckdb_query("SELECT 1")
        client.duckdb_insert("t", ["a"], [{"a": 1}])
        client.duckdb_tables()
        assert mock_client.request.call_count == 3

    def test_youtube_operations(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"title": "Test"})
        mock_client.post.return_value = _mock_response({"transcript": "text"})
        client.youtube_info("https://youtube.com/watch?v=abc")
        client.youtube_transcript("https://youtube.com/watch?v=abc")
        client.youtube_thumbnail("https://youtube.com/watch?v=abc")
        client.youtube_download_audio("https://youtube.com/watch?v=abc")
        client.youtube_download_video("https://youtube.com/watch?v=abc")
        client.youtube_job_status("job-123")
        # youtube_transcript uses _client.post, others use _client.request
        assert mock_client.request.call_count == 5

    def test_storage_operations(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response({"files": []})
        client.storage_list("prefix/")
        client.storage_delete(["key1"])
        assert mock_client.request.call_count == 2

    def test_storage_upload_requires_input(self):
        client, mock_client = _make_client(token="tok")
        with pytest.raises(ValueError, match="provide either"):
            client.storage_upload("key1")


# ── error handling ───────────────────────────────────────────────────

class TestApiClientErrors:
    def test_http_error_raises(self):
        client, mock_client = _make_client(token="tok")
        mock_client.request.return_value = _mock_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            client.search("test")


# ── list_endpoints ───────────────────────────────────────────────────

class TestListEndpoints:
    def test_list_endpoints_runs(self, capsys):
        ApiClient.list_endpoints()
        captured = capsys.readouterr()
        assert "POST" in captured.out
        assert "/search" in captured.out
