from __future__ import annotations

import asyncio
import gc
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tqdm import tqdm

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import (
    IngestedSourceRecord,
    IngestionRunRecord,
    SourceDocument,
    SourceManifest,
    SourceSeed,
)
from agentic_tour_planner.ingestion.connectors import SourceConnectors
from agentic_tour_planner.ingestion.wikivoyage_dump import WikivoyageDumpReader
from agentic_tour_planner.retrieval.chunker import chunk_text
from agentic_tour_planner.retrieval.graph_store import create_graph_store
from agentic_tour_planner.retrieval.vector_store import VectorStore
from agentic_tour_planner.storage.ingestion_store import SQLiteIngestionStore
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def _load_manifest(path: str | Path) -> SourceManifest:
    manifest_path = Path(path)
    logger.info(f"Loading manifest path={manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "name" in payload and "description" not in payload:
        payload["description"] = payload["name"]
    if "seeds" in payload:
        normalized_seeds = []
        for seed in payload["seeds"]:
            normalized_seed = dict(seed)
            if "kind" in normalized_seed and "source_type" not in normalized_seed:
                normalized_seed["source_type"] = normalized_seed.pop("kind")
            if "identifier" in normalized_seed:
                identifier = normalized_seed.pop("identifier")
                normalized_seed.setdefault("destination", str(identifier))
                normalized_seed.setdefault("title", str(identifier))
                if normalized_seed.get("source_type") == "wikivoyage":
                    normalized_seed.setdefault(
                        "url",
                        f"https://en.wikivoyage.org/wiki/{str(identifier).replace(' ', '_')}",
                    )
            normalized_seeds.append(normalized_seed)
        payload["seeds"] = normalized_seeds
    logger.debug(f"Manifest loaded seeds={len(payload.get('seeds', []))}")
    return SourceManifest.model_validate(payload)


class IngestionService:
    def __init__(self, vector_store: VectorStore | None = None, graph_store=None) -> None:
        self.settings = get_settings()
        self.connectors = SourceConnectors()
        self.vector_store = vector_store or VectorStore()
        self.graph_store = graph_store or create_graph_store()
        self.store = SQLiteIngestionStore()
        logger.debug("Initialized IngestionService")

    def _persist(
        self, seed: SourceSeed, document: SourceDocument, content_hash: str, chunk_count: int
    ) -> IngestedSourceRecord:
        logger.debug(
            f"Persisting source source_id={document.source_id} content_hash={content_hash} chunk_count={chunk_count}"
        )
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
        logger.debug(f"Fetching seed source_type={seed.source_type} destination={seed.destination} url={seed.url}")
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
        logger.info(f"Ingesting seed source_id={self._source_key(seed)} source_type={seed.source_type} force={force}")
        if not self.store.should_refresh(seed, force=force):
            logger.debug(f"Seed skip (no refresh needed) source_id={self._source_key(seed)}")
            return None
        document = await self._fetch_seed(seed)
        content_hash = self._content_hash(document)
        existing = self.store.get_source(self._source_key(seed))
        if existing and existing.content_hash == content_hash and not force:
            logger.debug(f"Seed skip (unchanged) source_id={self._source_key(seed)}")
            return existing
        self.vector_store.delete_source(document.source_id)
        self.graph_store.delete_source(document.source_id)
        chunk_count = self.vector_store.upsert_documents([document])
        self.graph_store.upsert_documents([document])
        record = self._persist(seed, document, content_hash, chunk_count)
        logger.info(f"Ingested seed source_id={self._source_key(seed)} chunk_count={chunk_count}")
        return record

    async def ingest_manifest(
        self, path: str | Path, force: bool = False, limit: int | None = None
    ) -> IngestionRunRecord:
        logger.info(f"Ingesting manifest path={path} force={force} limit={limit}")
        manifest: SourceManifest = _load_manifest(path)
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
                    logger.error(f"Failed to ingest seed source_key={self._source_key(seed)} error={exc}")
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
        logger.info(
            f"Ingestion run finished run_id={run.run_id} indexed={run.indexed_sources} skipped={run.skipped_sources} failed={run.failed_sources}"
        )
        return run

    def ingest_wikivoyage_dump(
        self,
        raw_dir: str | Path | None = None,
        *,
        force: bool = False,
        limit: int | None = None,
        batch_size: int | None = None,
    ) -> IngestionRunRecord:
        logger.info(f"Ingesting Wikivoyage dump raw_dir={raw_dir} limit={limit} batch_size={batch_size}")
        dump_path = self._resolve_wikivoyage_dump_path(raw_dir)
        resolved_batch_size = batch_size or int(getattr(self.settings, "wikivoyage_dump_batch_size", 64))
        reader = WikivoyageDumpReader(
            dump_path,
            min_content_chars=int(getattr(self.settings, "wikivoyage_dump_min_content_chars", 200)),
            include_redirects=bool(getattr(self.settings, "wikivoyage_dump_include_redirects", False)),
        )
        total_documents = reader.count_documents(limit=limit) if limit is None else limit
        run = IngestionRunRecord(run_id=str(uuid4()))
        self.store.start_run(run)

        batch: list[SourceDocument] = []
        with tqdm(total=total_documents, desc="Ingesting Wikivoyage dump", unit="docs") as pbar:
            for document in reader.iter_documents(limit=limit):
                run.total_sources += 1
                batch.append(document)
                if len(batch) >= resolved_batch_size:
                    batch_size_to_process = len(batch)
                    self._ingest_dump_batch(batch, run)
                    batch.clear()
                    gc.collect()
                    pbar.update(batch_size_to_process)
            if batch:
                batch_size_to_process = len(batch)
                self._ingest_dump_batch(batch, run)
                batch.clear()
                gc.collect()
                pbar.update(batch_size_to_process)

            pbar.set_postfix(
                {
                    "indexed": run.indexed_sources,
                    "skipped": run.skipped_sources,
                    "failed": run.failed_sources,
                }
            )

        run.finished_at = datetime.now(UTC)
        self.store.finish_run(run)
        logger.info(
            f"Wikivoyage dump run finished run_id={run.run_id} indexed={run.indexed_sources} skipped={run.skipped_sources} failed={run.failed_sources}"
        )
        return run

    def insert_or_update_dump(
        self,
        raw_dir: str | Path | None = None,
        limit: int | None = None,
        batch_size: int | None = None,
    ) -> IngestionRunRecord:
        logger.info(f"Inserting/updating Wikivoyage dump raw_dir={raw_dir} limit={limit} batch_size={batch_size}")
        dump_path = self._resolve_wikivoyage_dump_path(raw_dir)
        resolved_batch_size = batch_size or int(getattr(self.settings, "wikivoyage_dump_batch_size", 64))
        reader = WikivoyageDumpReader(
            dump_path,
            min_content_chars=int(getattr(self.settings, "wikivoyage_dump_min_content_chars", 200)),
            include_redirects=bool(getattr(self.settings, "wikivoyage_dump_include_redirects", False)),
        )
        total_documents = reader.count_documents(limit=limit) if limit is None else limit
        run = IngestionRunRecord(run_id=str(uuid4()))
        self.store.start_run(run)

        batch: list[SourceDocument] = []
        with tqdm(total=total_documents, desc="Processing Wikivoyage dump", unit="docs") as pbar:
            for document in reader.iter_documents(limit=limit):
                run.total_sources += 1
                batch.append(document)
                if len(batch) >= resolved_batch_size:
                    batch_size_to_process = len(batch)
                    self._ingest_dump_batch(batch, run)
                    batch.clear()
                    gc.collect()
                    pbar.update(batch_size_to_process)
            if batch:
                batch_size_to_process = len(batch)
                self._ingest_dump_batch(batch, run)
                batch.clear()
                gc.collect()
                pbar.update(batch_size_to_process)

            pbar.set_postfix(
                {
                    "inserted": run.indexed_sources,
                    "updated": run.indexed_sources,
                    "skipped": run.skipped_sources,
                    "failed": run.failed_sources,
                }
            )

        run.finished_at = datetime.now(UTC)
        self.store.finish_run(run)
        logger.info(
            f"Dump insert/update run finished run_id={run.run_id} indexed={run.indexed_sources} skipped={run.skipped_sources} failed={run.failed_sources}"
        )
        return run

    def _ingest_dump_batch(self, documents: list[SourceDocument], run: IngestionRunRecord) -> None:
        logger.debug(f"Ingesting dump batch size={len(documents)}")
        changed: list[tuple[SourceSeed, SourceDocument, str, int]] = []
        for document in documents:
            seed = self._seed_from_dump_document(document)
            content_hash = self._content_hash(document)
            existing = self.store.get_source(self._source_key(seed))
            if existing and existing.content_hash == content_hash:
                run.skipped_sources += 1
                continue
            chunk_count = len(
                list(
                    chunk_text(
                        document.content,
                        chunk_size=self.settings.chunk_size,
                        overlap=self.settings.chunk_overlap,
                    )
                )
            )
            changed.append((seed, document, content_hash, chunk_count))

        if not changed:
            return

        for _, document, _, _ in changed:
            self.vector_store.delete_source(document.source_id)
            self.graph_store.delete_source(document.source_id)
        docs_to_index = [document for _, document, _, _ in changed]
        self.vector_store.upsert_documents(docs_to_index)
        self.graph_store.upsert_documents(docs_to_index)
        for seed, document, content_hash, chunk_count in changed:
            self._persist(seed, document, content_hash, chunk_count)
            run.indexed_sources += 1
            run.indexed_chunks += chunk_count
        changed.clear()
        docs_to_index.clear()

    @staticmethod
    def _seed_from_dump_document(document: SourceDocument) -> SourceSeed:
        destination = str(document.metadata.get("destination") or document.title.replace(" travel guide", ""))
        return SourceSeed(
            destination=destination,
            title=document.title,
            url=document.url or f"https://en.wikivoyage.org/wiki/{destination.replace(' ', '_')}",
            source_type="wikivoyage",
            tags=["wikivoyage", "wikivoyage-dump", destination.lower()],
            metadata={
                "page_id": document.metadata.get("page_id"),
                "source": "wikivoyage_dump",
                "parent": document.metadata.get("parent"),
            },
        )

    def _resolve_wikivoyage_dump_path(self, raw_dir: str | Path | None = None) -> Path:
        logger.debug(f"Resolving Wikivoyage dump path raw_dir={raw_dir}")
        configured = getattr(self.settings, "wikivoyage_dump_path", None)
        if configured:
            path = Path(configured)
            if path.exists():
                logger.debug(f"Resolved dump path (configured) path={path}")
                return path
        base_dir = Path(raw_dir) if raw_dir is not None else self.settings.knowledge_base_dir / "raw"
        candidates = [
            base_dir / "enwikivoyage-latest-pages-articles.xml.bz2",
            base_dir / "enwikivoyage-latest-pages-articles-multistream.xml.bz2",
        ]
        for candidate in candidates:
            if candidate.exists():
                logger.debug(f"Resolved dump path (candidate) path={candidate}")
                return candidate
        raise FileNotFoundError(f"No Wikivoyage XML dump found in {base_dir}")

    def list_sources(self, limit: int = 100) -> list[IngestedSourceRecord]:
        return self.store.list_sources(limit=limit)

    async def ingest_wikivoyage(self, destination: str) -> IngestedSourceRecord | None:
        logger.info(f"Ingesting Wikivoyage destination={destination}")
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
        logger.info(f"Ingesting web url={url}")
        return await self.ingest_seed(
            SourceSeed(title=url, url=url, source_type="web", tags=["web"]),
            force=True,
        )

    async def ingest_youtube(self, url: str) -> IngestedSourceRecord | None:
        logger.info(f"Ingesting YouTube url={url}")
        return await self.ingest_seed(
            SourceSeed(title=url, url=url, source_type="youtube", tags=["youtube"]),
            force=True,
        )

    async def ingest_file(self, path: str) -> IngestedSourceRecord | None:
        file_path = Path(path)
        logger.info(f"Ingesting file path={file_path}")
        return await self.ingest_seed(
            SourceSeed(title=file_path.name, url=str(file_path), source_type="file", tags=["file"]),
            force=True,
        )
