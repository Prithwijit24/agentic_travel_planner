from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import IngestedSourceRecord, IngestionRunRecord, SourceSeed


class SQLiteIngestionStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._initialize()
        self._source_columns = self._table_columns("ingested_sources")
        self._run_columns = self._table_columns("ingestion_runs")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.operations_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingested_sources (
                    source_id TEXT PRIMARY KEY,
                    source_key TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    destination TEXT,
                    source_type TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    last_ingested_at TEXT NOT NULL,
                    error_message TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    total_sources INTEGER NOT NULL,
                    indexed_sources INTEGER NOT NULL,
                    skipped_sources INTEGER NOT NULL,
                    failed_sources INTEGER NOT NULL,
                    indexed_chunks INTEGER NOT NULL
                )
                """
            )

    def _table_columns(self, table_name: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def start_run(self, run: IngestionRunRecord) -> None:
        with self._connect() as conn:
            if "manifest_name" in self._run_columns:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ingestion_runs
                    (run_id, manifest_name, started_at, finished_at, status, total_sources, indexed_sources, skipped_sources, failed_sources, indexed_chunks)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        "manual",
                        run.started_at.isoformat(),
                        run.finished_at.isoformat() if run.finished_at else None,
                        "running",
                        run.total_sources,
                        run.indexed_sources,
                        run.skipped_sources,
                        run.failed_sources,
                        run.indexed_chunks,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ingestion_runs
                    (run_id, started_at, finished_at, total_sources, indexed_sources, skipped_sources, failed_sources, indexed_chunks)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run.run_id,
                        run.started_at.isoformat(),
                        run.finished_at.isoformat() if run.finished_at else None,
                        run.total_sources,
                        run.indexed_sources,
                        run.skipped_sources,
                        run.failed_sources,
                        run.indexed_chunks,
                    ),
                )

    def finish_run(self, run: IngestionRunRecord) -> None:
        with self._connect() as conn:
            if "status" in self._run_columns:
                conn.execute(
                    """
                    UPDATE ingestion_runs
                    SET finished_at = ?, status = ?, total_sources = ?, indexed_sources = ?, skipped_sources = ?,
                        failed_sources = ?, indexed_chunks = ?
                    WHERE run_id = ?
                    """,
                    (
                        (run.finished_at or datetime.now(UTC)).isoformat(),
                        "completed",
                        run.total_sources,
                        run.indexed_sources,
                        run.skipped_sources,
                        run.failed_sources,
                        run.indexed_chunks,
                        run.run_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE ingestion_runs
                    SET finished_at = ?, total_sources = ?, indexed_sources = ?, skipped_sources = ?,
                        failed_sources = ?, indexed_chunks = ?
                    WHERE run_id = ?
                    """,
                    (
                        (run.finished_at or datetime.now(UTC)).isoformat(),
                        run.total_sources,
                        run.indexed_sources,
                        run.skipped_sources,
                        run.failed_sources,
                        run.indexed_chunks,
                        run.run_id,
                    ),
                )

    def get_source(self, source_key: str) -> IngestedSourceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingested_sources WHERE source_key = ?",
                (source_key,),
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        if "source_id" in record:
            return IngestedSourceRecord(
                source_id=record["source_id"],
                source_key=record["source_key"],
                title=record["title"],
                url=record.get("url"),
                destination=record.get("destination"),
                source_type=record["source_type"],
                tags=json.loads(record["tags_json"]),
                content_hash=record["content_hash"],
                chunk_count=record["chunk_count"],
                last_ingested_at=datetime.fromisoformat(record["last_ingested_at"]),
                error_message=record.get("error_message"),
                metadata=json.loads(record.get("metadata_json", "{}")),
            )
        return IngestedSourceRecord(
            source_id=record["identifier"],
            source_key=record["source_key"],
            title=record.get("title") or record["identifier"],
            url=record.get("url"),
            destination=record.get("destination"),
            source_type=record["kind"],
            tags=json.loads(record["tags_json"]),
            content_hash=record["content_hash"],
            chunk_count=record["indexed_chunks"],
            last_ingested_at=datetime.fromisoformat(record["last_ingested_at"]),
            error_message=record.get("error_message"),
            metadata={"status": record.get("status"), "refresh_days": record.get("refresh_days")},
        )

    def upsert_source(self, record: IngestedSourceRecord) -> None:
        with self._connect() as conn:
            if "source_id" in self._source_columns:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ingested_sources
                    (source_id, source_key, title, url, destination, source_type, tags_json, content_hash, chunk_count, last_ingested_at, error_message, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.source_id,
                        record.source_key,
                        record.title,
                        str(record.url) if record.url else None,
                        record.destination,
                        record.source_type,
                        json.dumps(record.tags),
                        record.content_hash,
                        record.chunk_count,
                        record.last_ingested_at.isoformat(),
                        record.error_message,
                        json.dumps(record.metadata),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ingested_sources
                    (source_key, kind, identifier, title, url, destination, content_hash, indexed_chunks, status, refresh_days, tags_json, last_ingested_at, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.source_key,
                        record.source_type,
                        record.source_id,
                        record.title,
                        str(record.url) if record.url else None,
                        record.destination,
                        record.content_hash,
                        record.chunk_count,
                        "indexed" if not record.error_message else "failed",
                        int(record.metadata.get("refresh_days", 14)),
                        json.dumps(record.tags),
                        record.last_ingested_at.isoformat(),
                        record.error_message,
                    ),
                )

    def should_refresh(self, seed: SourceSeed, force: bool = False) -> bool:
        if force:
            return True
        existing = self.get_source(self.source_key(seed))
        if not existing:
            return True
        age = datetime.now(UTC) - existing.last_ingested_at.replace(tzinfo=UTC)
        return age >= timedelta(days=seed.refresh_days)

    def list_sources(self, limit: int = 100) -> list[IngestedSourceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source_key FROM ingested_sources
                ORDER BY last_ingested_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        records = []
        for row in rows:
            record = self.get_source(row["source_key"])
            if record is not None:
                records.append(record)
        return records

    @staticmethod
    def source_key(seed: SourceSeed) -> str:
        destination = (seed.destination or "").strip().lower()
        return f"{seed.source_type}:{destination}:{str(seed.url).strip().lower()}"
