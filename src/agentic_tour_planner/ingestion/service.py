from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import (
    IngestedSourceRecord,
    IngestionRunRecord,
    SourceDocument,
    SourceManifest,
    SourceSeed,
)
from agentic_tour_planner.ingestion.connectors import SourceConnectors
from agentic_tour_planner.ingestion.manifest import load_manifest
from agentic_tour_planner.retrieval.vector_store import VectorStore
from agentic_tour_planner.storage.ingestion_store import SQLiteIngestionStore


class IngestionService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.connectors = SourceConnectors()
        self.vector_store = VectorStore()
        self.store = SQLiteIngestionStore()

    def _persist(self, seed: SourceSeed, document: SourceDocument, content_hash: str, chunk_count: int) -> IngestedSourceRecord:
        record = IngestedSourceRecord(
            source_id=document.source_id,
            source_key=self._source_key(seed),
            title=document.title,
            url=document.url,
            destination=seed.destination,
            source_type=document.source_type,
            tags=seed.tags,
            content_hash=content_hash,
            chunk_count=chunk_count,
            last_ingested_at=datetime.now(UTC),
            metadata={**seed.metadata, **document.metadata},
        )
        self.store.upsert_source(record)
        return record

    @staticmethod
    def _content_hash(document: SourceDocument) -> str:
        return hashlib.sha256(document.content.encode("utf-8")).hexdigest()

    def _source_key(self, seed: SourceSeed) -> str:
        return self.store.source_key(seed)

    async def _fetch_seed(self, seed: SourceSeed) -> SourceDocument:
        if seed.source_type == "wikivoyage":
            if not seed.destination:
                raise ValueError("Wikivoyage ingestion requires a destination")
            return await self.connectors.fetch_wikivoyage(seed.destination)
        if seed.source_type == "youtube":
            return await self.connectors.fetch_youtube_transcript(str(seed.url))
        if seed.source_type == "file":
            return await self.connectors.fetch_file_document(str(seed.url))
        return await self.connectors.fetch_web_document(
            url=str(seed.url),
            source_id=self._source_key(seed),
            title=seed.title,
            source_type=seed.source_type,
            crawl_backend=seed.crawl_backend,
        )

    async def ingest_seed(self, seed: SourceSeed, force: bool = False) -> IngestedSourceRecord | None:
        if not self.store.should_refresh(seed, force=force):
            return None
        document = await self._fetch_seed(seed)
        content_hash = self._content_hash(document)
        existing = self.store.get_source(self._source_key(seed))
        if existing and existing.content_hash == content_hash and not force:
            return existing
        self.vector_store.delete_source(document.source_id)
        chunk_count = self.vector_store.upsert_documents([document])
        return self._persist(seed, document, content_hash, chunk_count)

    async def ingest_manifest(self, path: str | Path, force: bool = False, limit: int | None = None) -> IngestionRunRecord:
        manifest: SourceManifest = load_manifest(path)
        seeds = sorted(manifest.seeds, key=lambda seed: seed.priority)
        if limit is not None:
            seeds = seeds[:limit]
        normalized_seeds = [
            SourceSeed.model_validate(
                {
                    **seed.model_dump(),
                    "crawl_backend": seed.crawl_backend or manifest.defaults.crawl_backend,
                    "refresh_days": seed.refresh_days or manifest.defaults.refresh_days,
                    "tags": list(dict.fromkeys([*manifest.defaults.tags, *seed.tags])),
                }
            )
            for seed in seeds
        ]

        run = IngestionRunRecord(run_id=str(uuid4()), total_sources=len(normalized_seeds))
        self.store.start_run(run)
        semaphore = asyncio.Semaphore(manifest.defaults.max_concurrency or self.settings.crawl_max_concurrency)

        async def _run(seed: SourceSeed) -> tuple[str, IngestedSourceRecord | None]:
            async with semaphore:
                try:
                    result = await self.ingest_seed(seed, force=force)
                    return "indexed" if result else "skipped", result
                except Exception as exc:
                    failure = IngestedSourceRecord(
                        source_id=str(uuid4()),
                        source_key=self._source_key(seed),
                        title=seed.title,
                        url=seed.url,
                        destination=seed.destination,
                        source_type=seed.source_type,
                        tags=seed.tags,
                        content_hash="",
                        error_message=str(exc),
                    )
                    self.store.upsert_source(failure)
                    return "failed", failure

        for status, result in await asyncio.gather(*[_run(seed) for seed in normalized_seeds]):
            if status == "indexed" and result:
                run.indexed_sources += 1
                run.indexed_chunks += result.chunk_count
            elif status == "skipped":
                run.skipped_sources += 1
            else:
                run.failed_sources += 1

        run.finished_at = datetime.now(UTC)
        self.store.finish_run(run)
        return run

    def list_sources(self, limit: int = 100) -> list[IngestedSourceRecord]:
        return self.store.list_sources(limit=limit)

    async def ingest_wikivoyage(self, destination: str) -> IngestedSourceRecord | None:
        return await self.ingest_seed(
            SourceSeed(
                destination=destination,
                title=f"{destination} Wikivoyage",
                url=f"https://en.wikivoyage.org/wiki/{destination.replace(' ', '_')}",
                source_type="wikivoyage",
                tags=["wikivoyage", destination.lower()],
            ),
            force=True,
        )

    async def ingest_web(self, url: str) -> IngestedSourceRecord | None:
        return await self.ingest_seed(
            SourceSeed(title=url, url=url, source_type="web", tags=["web"]),
            force=True,
        )

    async def ingest_youtube(self, url: str) -> IngestedSourceRecord | None:
        return await self.ingest_seed(
            SourceSeed(title=url, url=url, source_type="youtube", tags=["youtube"]),
            force=True,
        )

    async def ingest_file(self, path: str) -> IngestedSourceRecord | None:
        file_path = Path(path)
        return await self.ingest_seed(
            SourceSeed(title=file_path.name, url=str(file_path), source_type="file", tags=["file"]),
            force=True,
        )
