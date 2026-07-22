from __future__ import annotations

import hashlib

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.retrieval.chunker import chunk_text
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

try:
    import chromadb
    from fastembed import TextEmbedding
except Exception:  # pragma: no cover
    chromadb = None
    TextEmbedding = None


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._fallback_documents: dict[str, SourceDocument] = {}
        self._collection = None
        self._embedder = None
        if chromadb and TextEmbedding:
            client = chromadb.PersistentClient(path=str(self.settings.vector_store_dir))
            self._collection = client.get_or_create_collection(name=self.settings.collection_name)
            self._embedder = TextEmbedding(model_name=self.settings.embedding_model_name)
            logger.debug("VectorStore: initialized chromadb backend (collection={})", self.settings.collection_name)
        else:
            logger.debug("VectorStore: chromadb/TextEmbedding unavailable, using in-memory fallback")

    @staticmethod
    def _chunk_id(source_id: str, chunk: str) -> str:
        logger.debug("chunk_id: source_id={} chunk_len={}", source_id, len(chunk))
        return hashlib.sha1(f"{source_id}:{chunk}".encode()).hexdigest()

    @staticmethod
    def _sanitize_metadata(metadata: dict) -> dict:
        logger.debug("sanitize_metadata: {} keys", len(metadata))
        sanitized = {}
        for key, value in metadata.items():
            if isinstance(value, list):
                if len(value) == 0:
                    continue
            if value is None:
                continue
            sanitized[key] = value
        return sanitized

    def delete_source(self, source_id: str) -> None:
        logger.info("delete_source: source_id={}", source_id)
        if self._collection:
            self._collection.delete(where={"source_id": source_id})
        stale_ids = [doc_id for doc_id, doc in self._fallback_documents.items() if doc.source_id == source_id]
        for doc_id in stale_ids:
            del self._fallback_documents[doc_id]

    def upsert_documents(self, documents: list[SourceDocument]) -> int:
        logger.info("upsert_documents: {} documents", len(documents))
        chunked_docs: list[tuple[str, SourceDocument]] = []
        for document in documents:
            for chunk in chunk_text(
                document.content,
                chunk_size=self.settings.chunk_size,
                overlap=self.settings.chunk_overlap,
            ):
                chunk_id = self._chunk_id(document.source_id, chunk)
                chunked_docs.append(
                    (
                        chunk_id,
                        SourceDocument(
                            source_id=document.source_id,
                            source_type=document.source_type,
                            title=document.title,
                            content=chunk,
                            url=document.url,
                            metadata={**document.metadata, "parent_title": document.title},
                        ),
                    )
                )

        if self._collection and self._embedder:
            logger.debug("upsert_documents: embedding {} chunks", len(chunked_docs))
            embeddings = list(self._embedder.embed([doc.content for _, doc in chunked_docs]))
            self._collection.upsert(
                ids=[doc_id for doc_id, _ in chunked_docs],
                documents=[doc.content for _, doc in chunked_docs],
                metadatas=[
                    self._sanitize_metadata(
                        {
                            **doc.metadata,
                            "source_id": doc.source_id,
                            "source_type": doc.source_type,
                            "title": doc.title,
                            "url": str(doc.url or ""),
                        }
                    )
                    for _, doc in chunked_docs
                ],
                embeddings=embeddings,
            )
            logger.info("upsert_documents: indexed {} chunks via chromadb", len(chunked_docs))
        else:
            for doc_id, doc in chunked_docs:
                self._fallback_documents[doc_id] = doc
            logger.info("upsert_documents: stored {} chunks in fallback", len(chunked_docs))
        return len(chunked_docs)

    def retrieve(self, query: str, top_k: int) -> list[SourceDocument]:
        logger.info("retrieve: top_k={} query_len={}", top_k, len(query))
        if self._collection and self._embedder:
            embedding = list(self._embedder.embed([query]))[0]
            result = self._collection.query(
                query_embeddings=[embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )
            docs: list[SourceDocument] = []
            for content, metadata, distance in zip(
                result.get("documents", [[]])[0],
                result.get("metadatas", [[]])[0],
                result.get("distances", [[]])[0],
                strict=False,
            ):
                docs.append(
                    SourceDocument(
                        source_id=metadata["source_id"],
                        source_type=metadata["source_type"],
                        title=metadata["title"],
                        url=metadata.get("url") or None,
                        content=content,
                        metadata={**metadata, "score": 1.0 / (1.0 + float(distance or 0.0))},
                    )
                )
            return docs

        logger.debug(
            "retrieve: chromadb unavailable, using lexical fallback over {} docs", len(self._fallback_documents)
        )
        query_terms = set(query.lower().split())
        scored = []
        for doc_id, doc in self._fallback_documents.items():
            overlap = len(query_terms.intersection(doc.content.lower().split()))
            scored.append((overlap, doc_id, doc))
        return [doc for _, _, doc in sorted(scored, reverse=True)[:top_k]]
