from __future__ import annotations

import hashlib

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.retrieval.chunker import chunk_text

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

    @staticmethod
    def _chunk_id(source_id: str, chunk: str) -> str:
        return hashlib.sha1(f"{source_id}:{chunk}".encode("utf-8")).hexdigest()

    def delete_source(self, source_id: str) -> None:
        if self._collection:
            self._collection.delete(where={"source_id": source_id})
        stale_ids = [doc_id for doc_id, doc in self._fallback_documents.items() if doc.source_id == source_id]
        for doc_id in stale_ids:
            del self._fallback_documents[doc_id]

    def upsert_documents(self, documents: list[SourceDocument]) -> int:
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
            embeddings = list(self._embedder.embed([doc.content for _, doc in chunked_docs]))
            self._collection.upsert(
                ids=[doc_id for doc_id, _ in chunked_docs],
                documents=[doc.content for _, doc in chunked_docs],
                metadatas=[
                    {
                        **doc.metadata,
                        "source_id": doc.source_id,
                        "source_type": doc.source_type,
                        "title": doc.title,
                        "url": str(doc.url or ""),
                    }
                    for _, doc in chunked_docs
                ],
                embeddings=embeddings,
            )
        else:
            for doc_id, doc in chunked_docs:
                self._fallback_documents[doc_id] = doc
        return len(chunked_docs)

    def retrieve(self, query: str, top_k: int) -> list[SourceDocument]:
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

        query_terms = set(query.lower().split())
        scored = []
        for doc_id, doc in self._fallback_documents.items():
            overlap = len(query_terms.intersection(doc.content.lower().split()))
            scored.append((overlap, doc_id, doc))
        return [doc for _, _, doc in sorted(scored, reverse=True)[:top_k]]

