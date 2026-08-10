"""ChromaDB client wrapper for the vector database.

Provides a persistent client with one collection for POI descriptions.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import chromadb
from loguru import logger

from agentic_tour_planner.config.settings import get_settings

COLLECTION_NAME = "poi_descriptions"


class VectorDBClient:
    """Wrapper around a persistent ChromaDB client."""

    def __init__(self, persist_dir: str) -> None:
        self._path = persist_dir
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=persist_dir)
        logger.info(f"ChromaDB initialized: {persist_dir}")

    def get_collection(self):
        return self._client.get_or_create_collection(name=COLLECTION_NAME)

    def add_pois(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        """Add POI embeddings in batches."""
        if not ids:
            return
        collection = self.get_collection()
        batch_size = 200
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_docs = documents[i:i + batch_size]
            batch_meta = metadatas[i:i + batch_size]
            collection.add(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)

    def query(self, query_text: str, n_results: int = 10, where: dict | None = None) -> dict:
        """Query the collection by text similarity."""
        collection = self.get_collection()
        kwargs = {"query_texts": [query_text], "n_results": n_results}
        if where:
            kwargs["where"] = where
        return collection.query(**kwargs)

    def count(self) -> int:
        return self.get_collection().count()

    def upsert(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        """Upsert POI embeddings (insert or update)."""
        if not ids:
            return
        collection = self.get_collection()
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def get_by_ids(self, ids: list[str]) -> dict:
        """Get documents by IDs."""
        collection = self.get_collection()
        return collection.get(ids=ids)


@lru_cache(maxsize=1)
def get_vector_db() -> VectorDBClient:
    settings = get_settings()
    persist_dir = getattr(settings, "chroma_persist_dir", "src/agentic_tour_planner/data/chroma")
    return VectorDBClient(persist_dir=persist_dir)
