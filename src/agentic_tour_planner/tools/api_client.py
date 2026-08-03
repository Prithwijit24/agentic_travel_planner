"""AI Infra Stack — Python API client (curl-style wrapper)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar, cast

import httpx

# dotenv loaded in __main__ block only

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_ADMIN_USER = "admin"


class ApiClient:
    """Base class: curl-like wrapper around the AI Infra Stack API."""

    ENDPOINT_INDEX: ClassVar[dict[str, tuple[str, str]]] = {
        "login": ("POST", "/auth/token"),
        "create_api_key": ("POST", "/auth/apikey"),
        "delete_api_key": ("DELETE", "/auth/apikey"),
        "list_api_keys": ("GET", "/auth/apikeys"),
        "rate_status": ("GET", "/auth/rate-status"),
        "search": ("POST", "/search"),
        "browse": ("POST", "/browse"),
        "crawl": ("POST", "/crawl"),
        "pipeline": ("POST", "/pipeline"),
        "stream_pipeline": ("POST", "/pipeline/stream"),
        "embed": ("POST", "/embed"),
        "clip_text_embedding": ("POST", "/clip/text_embedding"),
        "clip_image_embedding": ("POST", "/clip/image_embedding"),
        "clip_similarity": ("POST", "/clip/similarity"),
        "images": ("POST", "/images"),
        "news": ("POST", "/news"),
        "videos": ("POST", "/videos"),
        "rerank": ("POST", "/rerank"),
        "cache_set": ("POST", "/cache/set"),
        "cache_get": ("GET", "/cache/get/{key}"),
        "cache_delete": ("DELETE", "/cache/delete/{key}"),
        "vector_upsert": ("POST", "/vector/upsert"),
        "vector_search": ("POST", "/vector/search"),
        "vector_delete": ("POST", "/vector/delete"),
        "graph_query": ("POST", "/graph/query"),
        "graph_add_node": ("POST", "/graph/add_node"),
        "graph_add_edge": ("POST", "/graph/add_edge"),
        "duckdb_query": ("POST", "/duckdb/query"),
        "duckdb_insert": ("POST", "/duckdb/insert"),
        "duckdb_tables": ("GET", "/duckdb/tables"),
        "storage_upload": ("POST", "/storage/upload"),
        "storage_download": ("GET", "/storage/download/{bucket}/{key}"),
        "storage_list": ("POST", "/storage/list"),
        "storage_delete": ("POST", "/storage/delete"),
        "youtube_info": ("POST", "/youtube/info"),
        "youtube_download_audio": ("POST", "/youtube/download/audio"),
        "youtube_download_video": ("POST", "/youtube/download/video"),
        "youtube_job_status": ("GET", "/youtube/jobs/{job_id}"),
        "youtube_transcript": ("POST", "/youtube/transcript"),
        "youtube_thumbnail": ("POST", "/youtube/thumbnail"),
    }

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.username = username or os.getenv("ADMIN_USER", DEFAULT_ADMIN_USER)
        self.password = password or os.getenv("ADMIN_PASS", "")
        self.token = token or os.getenv("AI_STACK_TOKEN", "")
        self.api_key = api_key or os.getenv("AI_STACK_API_KEY", "")
        if client is not None:
            self._client = client
            self.base_url = str(client.base_url).rstrip("/")
        else:
            self.base_url = (
                base_url or os.getenv("BASE_URL") or os.getenv("AI_STACK_BASE_URL") or DEFAULT_BASE_URL
            ).rstrip("/")
            self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    # ── lifecycle ───────────────────────────────────────────────────────────

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @classmethod
    def list_endpoints(cls) -> None:
        for name, (method, path) in cls.ENDPOINT_INDEX.items():
            print(f"{method:6} {path:45} {name}()")

    # ── low-level helpers ───────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"X-API-Key": self.api_key}
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def login(self) -> dict:
        resp = self._client.post(
            "/auth/token",
            json={"username": self.username, "password": self.password},
        )
        resp.raise_for_status()
        data = cast(dict[Any, Any], resp.json())
        self.token = data.get("access_token", "")
        return data

    def ensure_auth(self) -> None:
        if self.api_key:
            return
        if not self.token:
            self.login()

    def _request(self, method: str, path: str, *, authed: bool = True, **kwargs: Any) -> dict[Any, Any]:
        headers = dict(kwargs.pop("headers", {}))
        if authed:
            self.ensure_auth()
            headers.update(self._headers())
        resp = self._client.request(method, path, headers=headers, **kwargs)
        resp.raise_for_status()
        return cast(dict[Any, Any], resp.json())

    # ── core ────────────────────────────────────────────────────────────────

    def root(self) -> dict:
        return self._request("GET", "/", authed=False)

    def health(self) -> dict:
        return self._request("GET", "/health", authed=False)

    # ── auth ────────────────────────────────────────────────────────────────

    def create_api_key(self, name: str, rate_limit: int | None = None, expires_days: int | None = None) -> dict:
        return self._request(
            "POST", "/auth/apikey", json={"name": name, "rate_limit": rate_limit, "expires_days": expires_days}
        )

    def delete_api_key(self, key: str) -> dict:
        return self._request("DELETE", "/auth/apikey", params={"key": key})

    def list_api_keys(self) -> list:
        return cast(list, self._request("GET", "/auth/apikeys"))

    def rate_status(self) -> dict:
        return self._request("GET", "/auth/rate-status")

    # ── search / browse / crawl / pipeline ─────────────────────────────────

    def search(
        self, query: str, categories: str = "general", language: str = "en", max_results: int = 10, safesearch: int = 1
    ) -> dict:
        return self._request(
            "POST",
            "/search",
            json={
                "query": query,
                "categories": categories,
                "language": language,
                "max_results": max_results,
                "safesearch": safesearch,
            },
        )

    def browse(
        self,
        url: str,
        action: str = "content",
        selector: str | None = None,
        text: str | None = None,
        full_page: bool = True,
        wait_ms: int = 1000,
    ) -> dict:
        return self._request(
            "POST",
            "/browse",
            json={
                "url": url,
                "action": action,
                "selector": selector,
                "text": text,
                "full_page": full_page,
                "wait_ms": wait_ms,
            },
        )

    def crawl(
        self, url: str, only_main_content: bool = True, include_html: bool = False, timeout_ms: int = 30000
    ) -> dict:
        return self._request(
            "POST",
            "/crawl",
            json={
                "url": url,
                "only_main_content": only_main_content,
                "include_html": include_html,
                "timeout_ms": timeout_ms,
            },
        )

    def pipeline(
        self,
        query: str,
        top_k: int = 5,
        crawl_limit: int = 10,
        max_search_results: int = 15,
        max_markdown_chars: int = 5000,
        categories: str = "general",
        language: str = "en",
        crawl_timeout_ms: int = 15000,
    ) -> dict:
        return self._request(
            "POST",
            "/pipeline",
            json={
                "query": query,
                "top_k": top_k,
                "crawl_limit": crawl_limit,
                "max_search_results": max_search_results,
                "max_markdown_chars": max_markdown_chars,
                "categories": categories,
                "language": language,
                "crawl_timeout_ms": crawl_timeout_ms,
            },
        )

    def stream_pipeline(self, query: str, **options: Any) -> Iterator[dict]:
        self.ensure_auth()
        body = {"query": query, **options}
        with self._client.stream("POST", "/pipeline/stream", json=body, headers=self._headers()) as resp:
            resp.raise_for_status()
            event = None
            for line in resp.iter_lines():
                line = line.strip()
                if not line:
                    event = None
                    continue
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    payload = line[len("data:") :].strip()
                    if payload:
                        yield {"event": event, "data": json.loads(payload)}

    # ── embeddings & ML ─────────────────────────────────────────────────────

    def embed(self, texts: list[str], normalize: bool = True) -> dict:
        return self._request("POST", "/embed", json={"texts": texts, "normalize": normalize})

    def clip_text_embedding(self, texts: list[str]) -> dict:
        return self._request("POST", "/clip/text_embedding", json={"texts": texts})

    def clip_image_embedding(self, image_urls: list[str] | None = None, images_base64: list[str] | None = None) -> dict:
        body: dict[str, Any] = {}
        if image_urls is not None:
            body["image_urls"] = image_urls
        if images_base64 is not None:
            body["images_base64"] = images_base64
        return self._request("POST", "/clip/image_embedding", json=body)

    def clip_similarity(
        self, text: str, image_urls: list[str] | None = None, images_base64: list[str] | None = None
    ) -> dict:
        body: dict[str, Any] = {"text": text}
        if image_urls is not None:
            body["image_urls"] = image_urls
        if images_base64 is not None:
            body["images_base64"] = images_base64
        return self._request("POST", "/clip/similarity", json=body)

    # ── images (CLIP post-processing built-in) ─────────────────────────────

    def images(self, query: str, max_results: int = 10, use_clip: bool = True) -> dict:
        """POST /images — image search with optional CLIP reranking.

        Fallback chain: DDGS → Unsplash → Pexels.
        Each result gets a ``clip_score`` (0-1) when ``use_clip`` is True.
        """
        body: dict[str, Any] = {"query": query, "max_results": max_results, "use_clip": use_clip}
        return self._request("POST", "/images", json=body)

    # ── news ──────────────────────────────────────────────────────────────

    def news(self, query: str, max_results: int = 10, timelimit: str | None = None) -> dict:
        """POST /news — fetch recent news articles about a topic.

        Returns ``{"results": [...]}`` with title, url, source, published, body.
        """
        body: dict[str, Any] = {"query": query, "max_results": max_results}
        if timelimit is not None:
            body["timelimit"] = timelimit
        return self._request("POST", "/news", json=body)

    def videos(self, query: str, max_results: int = 10) -> dict:
        """POST /videos — search YouTube videos about a topic.

        Returns ``{"results": [...]}`` with title, url, publisher, duration, views.
        """
        return self._request("POST", "/videos", json={"query": query, "max_results": max_results})

    def rerank(self, query: str, documents: list[str], top_k: int | None = None) -> dict:
        body: dict[str, Any] = {"query": query, "documents": documents}
        if top_k is not None:
            body["top_k"] = top_k
        return self._request("POST", "/rerank", json=body)

    # ── cache (Redis) ───────────────────────────────────────────────────────

    def cache_set(self, key: str, value: Any, ttl_seconds: int | None = None) -> dict:
        body: dict[str, Any] = {"key": key, "value": value}
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        return self._request("POST", "/cache/set", json=body)

    def cache_get(self, key: str) -> dict:
        return self._request("GET", f"/cache/get/{key}")

    def cache_delete(self, key: str) -> dict:
        return self._request("DELETE", f"/cache/delete/{key}")

    # ── vector (ChromaDB) ───────────────────────────────────────────────────

    def vector_upsert(self, collection: str, records: list[dict]) -> dict:
        return self._request("POST", "/vector/upsert", json={"collection": collection, "records": records})

    def vector_search(
        self, collection: str, query_embedding: list[float], top_k: int = 5, where: dict | None = None
    ) -> dict:
        body: dict[str, Any] = {"collection": collection, "query_embedding": query_embedding, "top_k": top_k}
        if where is not None:
            body["where"] = where
        return self._request("POST", "/vector/search", json=body)

    def vector_delete(self, collection: str, ids: list[str]) -> dict:
        return self._request("POST", "/vector/delete", json={"collection": collection, "ids": ids})

    # ── graph (Neo4j) ───────────────────────────────────────────────────────

    def graph_query(self, cypher: str, parameters: dict | None = None) -> dict:
        return self._request("POST", "/graph/query", json={"cypher": cypher, "parameters": parameters or {}})

    def graph_add_node(self, label: str, properties: dict | None = None, merge_key: str | None = None) -> dict:
        return self._request(
            "POST", "/graph/add_node", json={"label": label, "properties": properties or {}, "merge_key": merge_key}
        )

    def graph_add_edge(
        self,
        from_label: str,
        from_key: str,
        from_value: Any,
        to_label: str,
        to_key: str,
        to_value: Any,
        relationship: str,
        properties: dict | None = None,
    ) -> dict:
        return self._request(
            "POST",
            "/graph/add_edge",
            json={
                "from_label": from_label,
                "from_key": from_key,
                "from_value": from_value,
                "to_label": to_label,
                "to_key": to_key,
                "to_value": to_value,
                "relationship": relationship,
                "properties": properties or {},
            },
        )

    # ── duckdb ──────────────────────────────────────────────────────────────

    def duckdb_query(self, sql: str, params: list | None = None) -> dict:
        return self._request("POST", "/duckdb/query", json={"sql": sql, "params": params})

    def duckdb_insert(self, table: str, columns: list[str], rows: list[dict]) -> dict:
        return self._request("POST", "/duckdb/insert", json={"table": table, "columns": columns, "rows": rows})

    def duckdb_tables(self) -> dict:
        return self._request("GET", "/duckdb/tables")

    # ── storage (MinIO / S3) ────────────────────────────────────────────────

    def storage_upload(
        self,
        key: str,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        bucket: str | None = None,
        content_type: str | None = None,
    ) -> dict:
        if file_path is None and file_bytes is None:
            raise ValueError("provide either file_path or file_bytes")
        self.ensure_auth()
        if file_path is not None:
            with Path(file_path).open("rb") as fh:
                payload = fh.read()
            fname = filename or Path(file_path).name
        else:
            payload = file_bytes or b""
            fname = filename or "upload.bin"
        data: dict[str, str] = {"key": key}
        if bucket:
            data["bucket"] = bucket
        if content_type:
            data["content_type"] = content_type
        resp = self._client.post(
            "/storage/upload", data=data, files={"file": (fname, payload, content_type)}, headers=self._headers()
        )
        resp.raise_for_status()
        return cast(dict[Any, Any], resp.json())

    def storage_download(self, bucket: str, key: str) -> httpx.Response:
        self.ensure_auth()
        return self._client.get(f"/storage/download/{bucket}/{key}", headers=self._headers())

    def storage_list(self, prefix: str = "", bucket: str | None = None) -> dict:
        return self._request("POST", "/storage/list", json={"prefix": prefix, "bucket": bucket})

    def storage_delete(self, keys: list[str], bucket: str | None = None) -> dict:
        return self._request("POST", "/storage/delete", json={"keys": keys, "bucket": bucket})

    # ── youtube ─────────────────────────────────────────────────────────────

    def youtube_info(self, url: str) -> dict:
        return self._request("POST", "/youtube/info", json={"url": url})

    def youtube_download_audio(self, url: str, quality: str = "best") -> dict:
        return self._request("POST", "/youtube/download/audio", json={"url": url, "quality": quality})

    def youtube_download_video(self, url: str, quality: str = "best") -> dict:
        return self._request("POST", "/youtube/download/video", json={"url": url, "quality": quality})

    def youtube_job_status(self, job_id: str) -> dict:
        return self._request("GET", f"/youtube/jobs/{job_id}")

    def youtube_transcript(
        self, url: str, language: str = "en", force_whisper: bool = False, output_format: str = "json"
    ) -> Any:
        resp = self._client.post(
            "/youtube/transcript",
            params={"output_format": output_format},
            json={"url": url, "language": language, "force_whisper": force_whisper},
            headers=self._headers(),
        )
        resp.raise_for_status()
        if output_format == "markdown":
            return resp.text
        return resp.json()

    def youtube_thumbnail(self, url: str) -> dict:
        return self._request("POST", "/youtube/thumbnail", json={"url": url})


if __name__ == "__main__":
    ApiClient.list_endpoints()
