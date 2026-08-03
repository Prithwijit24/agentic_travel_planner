"""Async wrapper around self-hosted AI Infra Stack."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_credential(setting_val: str | None, env_var: str) -> str | None:
    """Return setting value if non-empty, else fall back to env_var."""
    if setting_val:
        return setting_val
    return os.getenv(env_var) or None


class AiStackClient:
    """Thin async wrapper around the AI Infra Stack ApiClient.

    All methods return parsed JSON (dict/list) and raise
    ``httpx.HTTPStatusError`` on non-2xx responses.
    """

    def __init__(self) -> None:
        from agentic_tour_planner.tools.api_client import ApiClient

        settings = get_settings()
        password = _resolve_credential(
            getattr(settings, "ai_stack_admin_pass", None), "ADMIN_PASS"
        ) or _resolve_credential(getattr(settings, "admin_pass", None), "ADMIN_PASS")
        # The AI Infra Stack accepts an X-API-Key for most endpoints, so prefer
        # a dedicated key when configured; otherwise fall back to JWT login.
        # JWT_SECRET doubles as the X-API-Key for this deployment.
        api_key = _resolve_credential(
            getattr(settings, "ai_stack_api_key", None) or getattr(settings, "ai_stack_token", None),
            "AI_STACK_API_KEY",
        ) or _resolve_credential(getattr(settings, "jwt_secret", None), "JWT_SECRET")
        timeout = getattr(settings, "ai_stack_timeout_seconds", None) or 1000.0
        # The pipeline endpoint (search -> crawl -> rerank) can run for minutes,
        # so the client must not use the short 60s default timeout.
        self._client = ApiClient(
            base_url=getattr(settings, "ai_stack_base_url", None),
            username=getattr(settings, "ai_stack_admin_user", None),
            password=password,
            api_key=api_key,
            timeout=timeout,
        )
        logger.info(f"AiStackClient initialized: {self._client.base_url}")
        if api_key:
            logger.debug("AiStackClient using X-API-Key auth")

    # ── lifecycle ───────────────────────────────────────────────────────

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AiStackClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── core ────────────────────────────────────────────────────────────

    async def health(self) -> dict:
        """GET /health — per-service dependency health."""
        return await asyncio.to_thread(self._client.health)

    # ── search / browse / crawl / pipeline ──────────────────────────────

    async def search(
        self,
        query: str,
        categories: str = "general",
        language: str = "en",
        max_results: int = 10,
    ) -> dict:
        """POST /search — web search (SearXNG or DDGS)."""
        return await asyncio.to_thread(
            self._client.search,
            query,
            categories=categories,
            language=language,
            max_results=max_results,
        )

    async def browse(
        self,
        url: str,
        action: str = "content",
        selector: str | None = None,
        text: str | None = None,
        full_page: bool = True,
    ) -> dict:
        """POST /browse — automated browser (content/screenshot/click/fill_form)."""
        return await asyncio.to_thread(
            self._client.browse,
            url,
            action=action,
            selector=selector,
            text=text,
            full_page=full_page,
        )

    async def crawl(self, url: str) -> dict:
        """POST /crawl — extract clean markdown from a URL."""
        return await asyncio.to_thread(self._client.crawl, url)

    async def pipeline(
        self,
        query: str,
        top_k: int = 5,
        crawl_limit: int = 10,
        max_search_results: int = 15,
    ) -> dict:
        """POST /pipeline — search -> crawl -> rerank (non-streaming)."""
        return await asyncio.to_thread(
            self._client.pipeline,
            query,
            top_k=top_k,
            crawl_limit=crawl_limit,
            max_search_results=max_search_results,
        )

    async def stream_pipeline(self, query: str, **options: Any) -> Any:
        """POST /pipeline/stream — SSE streaming pipeline. Returns iterator."""
        return self._client.stream_pipeline(query, **options)

    # ── rerank / embed ─────────────────────────────────────────────────

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int | None = None,
    ) -> dict:
        """POST /rerank — cross-encoder relevance ranking."""
        return await asyncio.to_thread(
            self._client.rerank,
            query,
            documents,
            top_k=top_k,
        )

    async def embed(self, texts: list[str]) -> dict:
        """POST /embed — sentence-transformer text embeddings."""
        return await asyncio.to_thread(self._client.embed, texts)

    # ── CLIP ───────────────────────────────────────────────────────────

    async def clip_text_embedding(self, texts: list[str]) -> dict:
        """POST /clip/text_embedding — CLIP text encoder."""
        return await asyncio.to_thread(self._client.clip_text_embedding, texts)

    async def clip_image_embedding(
        self,
        image_urls: list[str] | None = None,
        images_base64: list[str] | None = None,
    ) -> dict:
        """POST /clip/image_embedding — CLIP vision encoder."""
        return await asyncio.to_thread(
            self._client.clip_image_embedding,
            image_urls=image_urls,
            images_base64=images_base64,
        )

    async def clip_similarity(
        self,
        text: str,
        image_urls: list[str] | None = None,
        images_base64: list[str] | None = None,
    ) -> dict:
        """POST /clip/similarity — softmax text->image similarity."""
        return await asyncio.to_thread(
            self._client.clip_similarity,
            text,
            image_urls=image_urls,
            images_base64=images_base64,
        )

    # ── images (CLIP post-processing built-in) ─────────────────────────

    async def images(
        self,
        query: str,
        max_results: int = 10,
        use_clip: bool = True,
    ) -> dict:
        """POST /images — image search with optional CLIP reranking.

        Fallback chain: DDGS → Unsplash → Pexels.
        Each result gets a clip_score (0-1) when use_clip is True.
        """
        return await asyncio.to_thread(
            self._client.images,
            query,
            max_results=max_results,
            use_clip=use_clip,
        )

    # ── news ──────────────────────────────────────────────────────────────

    async def news(
        self,
        query: str,
        max_results: int = 10,
        timelimit: str | None = None,
    ) -> dict:
        """POST /news — fetch recent news articles about a topic."""
        return await asyncio.to_thread(
            self._client.news,
            query,
            max_results=max_results,
            timelimit=timelimit,
        )

    async def videos(
        self,
        query: str,
        max_results: int = 10,
    ) -> dict:
        """POST /videos — search YouTube videos about a topic."""
        return await asyncio.to_thread(
            self._client.videos,
            query,
            max_results=max_results,
        )

    # ── cache (Redis) ──────────────────────────────────────────────────

    async def cache_set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> dict:
        """POST /cache/set — write a value to Redis."""
        return await asyncio.to_thread(
            self._client.cache_set,
            key,
            value,
            ttl_seconds=ttl_seconds,
        )

    async def cache_get(self, key: str) -> dict:
        """GET /cache/get/{key} — read a value from Redis."""
        return await asyncio.to_thread(self._client.cache_get, key)

    async def cache_delete(self, key: str) -> dict:
        """DELETE /cache/delete/{key} — remove a Redis key."""
        return await asyncio.to_thread(self._client.cache_delete, key)

    # ── vector (ChromaDB) ──────────────────────────────────────────────

    async def vector_upsert(
        self,
        collection: str,
        records: list[dict],
    ) -> dict:
        """POST /vector/upsert — insert/update embeddings."""
        return await asyncio.to_thread(
            self._client.vector_upsert,
            collection,
            records,
        )

    async def vector_search(
        self,
        collection: str,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> dict:
        """POST /vector/search — approximate nearest-neighbor search."""
        return await asyncio.to_thread(
            self._client.vector_search,
            collection,
            query_embedding,
            top_k=top_k,
        )

    async def vector_delete(self, collection: str, ids: list[str]) -> dict:
        """POST /vector/delete — delete embeddings by ID."""
        return await asyncio.to_thread(
            self._client.vector_delete,
            collection,
            ids,
        )

    # ── graph (Neo4j) ──────────────────────────────────────────────────

    async def graph_query(
        self,
        cypher: str,
        parameters: dict | None = None,
    ) -> dict:
        """POST /graph/query — run a parameterized Cypher query."""
        return await asyncio.to_thread(
            self._client.graph_query,
            cypher,
            parameters=parameters,
        )

    async def graph_add_node(
        self,
        label: str,
        properties: dict | None = None,
        merge_key: str | None = None,
    ) -> dict:
        """POST /graph/add_node — create or merge a node."""
        return await asyncio.to_thread(
            self._client.graph_add_node,
            label,
            properties=properties,
            merge_key=merge_key,
        )

    async def graph_add_edge(
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
        """POST /graph/add_edge — create a relationship between two nodes."""
        return await asyncio.to_thread(
            self._client.graph_add_edge,
            from_label,
            from_key,
            from_value,
            to_label,
            to_key,
            to_value,
            relationship,
            properties=properties,
        )

    # ── YouTube ────────────────────────────────────────────────────────

    async def youtube_info(self, url: str) -> dict:
        """POST /youtube/info — video metadata."""
        return await asyncio.to_thread(self._client.youtube_info, url)

    async def youtube_transcript(
        self,
        url: str,
        language: str = "en",
    ) -> dict:
        """POST /youtube/transcript — subtitles (Whisper fallback)."""
        return await asyncio.to_thread(
            self._client.youtube_transcript,
            url,
            language=language,
        )

    async def youtube_thumbnail(self, url: str) -> dict:
        """POST /youtube/thumbnail — thumbnail URL."""
        return await asyncio.to_thread(self._client.youtube_thumbnail, url)

    # ── DuckDB ─────────────────────────────────────────────────────────

    async def duckdb_query(
        self,
        sql: str,
        params: list | None = None,
    ) -> dict:
        """POST /duckdb/query — run SQL on DuckDB."""
        return await asyncio.to_thread(
            self._client.duckdb_query,
            sql,
            params=params,
        )

    # ── storage (MinIO/S3) ─────────────────────────────────────────────

    async def storage_list(
        self,
        prefix: str = "",
        bucket: str | None = None,
    ) -> dict:
        """POST /storage/list — list objects under a prefix."""
        return await asyncio.to_thread(
            self._client.storage_list,
            prefix,
            bucket=bucket,
        )

    # ── YouTube downloads ────────────────────────────────────────────

    async def youtube_download_audio(self, url: str, quality: str = "best") -> dict:
        """POST /youtube/download/audio — queue an mp3 download job."""
        return await asyncio.to_thread(
            self._client.youtube_download_audio,
            url,
            quality=quality,
        )

    async def youtube_download_video(self, url: str, quality: str = "best") -> dict:
        """POST /youtube/download/video — queue a video download job."""
        return await asyncio.to_thread(
            self._client.youtube_download_video,
            url,
            quality=quality,
        )

    async def youtube_job_status(self, job_id: str) -> dict:
        """GET /youtube/jobs/{job_id} — poll a download job."""
        return await asyncio.to_thread(self._client.youtube_job_status, job_id)

    # ── DuckDB extended ──────────────────────────────────────────────

    async def duckdb_insert(
        self,
        table: str,
        columns: list[str],
        rows: list[dict],
    ) -> dict:
        """POST /duckdb/insert — insert rows into a table."""
        return await asyncio.to_thread(
            self._client.duckdb_insert,
            table,
            columns,
            rows,
        )

    async def duckdb_tables(self) -> dict:
        """GET /duckdb/tables — list tables with columns and row counts."""
        return await asyncio.to_thread(self._client.duckdb_tables)

    # ── Storage (MinIO/S3) extended ──────────────────────────────────

    async def storage_upload(
        self,
        key: str,
        file_path: str | None = None,
        file_bytes: bytes | None = None,
        filename: str | None = None,
        bucket: str | None = None,
        content_type: str | None = None,
    ) -> dict:
        """POST /storage/upload — multipart upload."""
        return await asyncio.to_thread(
            self._client.storage_upload,
            key,
            file_path=file_path,
            file_bytes=file_bytes,
            filename=filename,
            bucket=bucket,
            content_type=content_type,
        )

    async def storage_download(self, bucket: str, key: str) -> Any:
        """GET /storage/download/{bucket}/{key} — stream an object."""
        return await asyncio.to_thread(
            self._client.storage_download,
            bucket,
            key,
        )

    async def storage_delete(
        self,
        keys: list[str],
        bucket: str | None = None,
    ) -> dict:
        """POST /storage/delete — delete objects by key."""
        return await asyncio.to_thread(
            self._client.storage_delete,
            keys,
            bucket=bucket,
        )
