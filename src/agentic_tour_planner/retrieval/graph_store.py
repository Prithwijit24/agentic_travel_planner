from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.utils.logging import get_logger


def _lexical_score(query: str, content: str) -> float:
    q = Counter(re.findall(r"[a-z0-9]+", query.lower()))
    d = Counter(re.findall(r"[a-z0-9]+", content.lower()))
    return float(sum(min(q[tok], d[tok]) for tok in q))


logger = get_logger(__name__)

try:
    from neo4j import GraphDatabase

    # Optional runtime dependency: keep a typed alias so mypy does not flag the
    # ``= None`` fallback as reassigning the imported class object.
    _GRAPH_DATABASE: Any = GraphDatabase
except Exception:  # pragma: no cover
    _GRAPH_DATABASE = None


GRAPH_METHODS = {"graph_fulltext", "graph_hierarchy", "graph_neighbors"}


def create_graph_store():
    settings = get_settings()
    backend = str(getattr(settings, "graph_store_backend", "memory")).lower()
    logger.info("create_graph_store: backend={}", backend)
    if backend == "neo4j":
        return Neo4jGraphStore()
    if backend == "disabled":
        return DisabledGraphStore()
    return InMemoryGraphStore()


class DisabledGraphStore:
    def delete_source(self, source_id: str) -> None:
        return None

    def upsert_documents(self, documents: list[SourceDocument]) -> int:
        return 0

    def retrieve(self, query: str, top_k: int, method: str = "graph_fulltext") -> list[SourceDocument]:
        return []


class InMemoryGraphStore:
    def __init__(self) -> None:
        self.documents: dict[str, SourceDocument] = {}
        self.title_to_source_id: dict[str, str] = {}
        self.parents: dict[str, str] = {}
        self.children: dict[str, set[str]] = defaultdict(set)
        self.links: dict[str, set[str]] = defaultdict(set)
        self.categories: dict[str, set[str]] = defaultdict(set)

    def upsert_documents(self, documents: list[SourceDocument]) -> int:
        logger.info("InMemoryGraphStore.upsert_documents: {} documents", len(documents))
        for document in documents:
            self.documents[document.source_id] = document
            title = _destination_name(document).lower()
            self.title_to_source_id[title] = document.source_id
            parent = _clean_metadata_text(document.metadata.get("parent"))
            if parent:
                self.parents[document.source_id] = parent
                self.children[parent.lower()].add(document.source_id)
            for category in _metadata_list(document.metadata.get("categories")):
                self.categories[category.lower()].add(document.source_id)
            for link in _metadata_list(document.metadata.get("links")):
                target_id = self.title_to_source_id.get(link.lower())
                if target_id:
                    self.links[document.source_id].add(target_id)
        return len(documents)

    def delete_source(self, source_id: str) -> None:
        logger.info("InMemoryGraphStore.delete_source: {}", source_id)
        document = self.documents.pop(source_id, None)
        if document:
            self.title_to_source_id.pop(_destination_name(document).lower(), None)
        parent = self.parents.pop(source_id, None)
        if parent:
            self.children[parent.lower()].discard(source_id)
        self.links.pop(source_id, None)
        for linked_ids in self.links.values():
            linked_ids.discard(source_id)
        for source_ids in self.categories.values():
            source_ids.discard(source_id)

    def retrieve(self, query: str, top_k: int, method: str = "graph_fulltext") -> list[SourceDocument]:
        logger.info("InMemoryGraphStore.retrieve: method={} top_k={} query_len={}", method, top_k, len(query))
        if method not in GRAPH_METHODS:
            raise ValueError(f"Unsupported graph retrieval method: {method}")
        scored: list[tuple[float, str, SourceDocument]] = []
        for source_id, document in self.documents.items():
            score = self._score_document(query, document, method)
            if score > 0:
                scored.append((score, source_id, self._with_graph_metadata(document, score, method)))
        results = [doc for _, _, doc in sorted(scored, reverse=True)[:top_k]]
        logger.debug("InMemoryGraphStore.retrieve: {} results", len(results))
        return results

    def _score_document(self, query: str, document: SourceDocument, method: str) -> float:
        logger.debug("score_document: source_id={} method={}", document.source_id, method)
        content = " ".join(
            [
                document.title,
                document.content,
                str(document.metadata.get("destination") or ""),
                str(document.metadata.get("parent") or ""),
                " ".join(_metadata_list(document.metadata.get("categories"))),
                " ".join(_metadata_list(document.metadata.get("headings"))),
            ]
        )
        score = _lexical_score(query, content)
        if method == "graph_hierarchy":
            score += 2.0 * _lexical_score(query, str(document.metadata.get("parent") or ""))
            score += _lexical_score(query, " ".join(_metadata_list(document.metadata.get("categories"))))
        elif method == "graph_neighbors":
            neighbor_text = []
            for neighbor_id in self.links.get(document.source_id, set()):
                neighbor = self.documents.get(neighbor_id)
                if neighbor:
                    neighbor_text.append(f"{neighbor.title} {neighbor.content}")
            parent = self.parents.get(document.source_id)
            if parent:
                neighbor_text.append(parent)
            score += 0.5 * _lexical_score(query, " ".join(neighbor_text))
        logger.debug("score_document: source_id={} score={:.3f}", document.source_id, score)
        return score

    @staticmethod
    def _with_graph_metadata(document: SourceDocument, score: float, method: str) -> SourceDocument:
        return SourceDocument(
            source_id=document.source_id,
            source_type=document.source_type,
            title=document.title,
            url=document.url,
            content=document.content,
            metadata={
                **document.metadata,
                "score": score,
                "graph_score": score,
                "graph_method": method,
                "retrieval_source": "graph",
            },
        )


class Neo4jGraphStore:
    def __init__(self) -> None:
        if _GRAPH_DATABASE is None:  # pragma: no cover
            raise RuntimeError("neo4j package is required when graph_store_backend is 'neo4j'")
        self.settings = get_settings()
        logger.debug(
            "Neo4jGraphStore: connecting to {} database={}",
            self.settings.neo4j_uri,
            getattr(self.settings, "neo4j_database", "neo4j"),
        )
        self.driver = _GRAPH_DATABASE.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        self.database = getattr(self.settings, "neo4j_database", "neo4j")
        self.fulltext_index = getattr(self.settings, "neo4j_fulltext_index", "travelDestinationText")
        self._ensure_schema()

    def close(self) -> None:
        logger.debug("Neo4jGraphStore.close")
        self.driver.close()

    def _ensure_schema(self) -> None:
        logger.debug("Neo4jGraphStore: ensuring schema ({} index)", self.fulltext_index)
        queries = [
            "CREATE CONSTRAINT destination_source_id IF NOT EXISTS FOR (d:Destination) REQUIRE d.source_id IS UNIQUE",
            "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT section_key IF NOT EXISTS FOR (s:Section) REQUIRE s.key IS UNIQUE",
            (
                f"CREATE FULLTEXT INDEX {self.fulltext_index} IF NOT EXISTS "
                "FOR (d:Destination) ON EACH [d.title, d.content, d.destination]"
            ),
        ]
        with self.driver.session(database=self.database) as session:
            for query in queries:
                session.run(query)

    def upsert_documents(self, documents: list[SourceDocument]) -> int:
        logger.info("Neo4jGraphStore.upsert_documents: {} documents", len(documents))
        with self.driver.session(database=self.database) as session:
            for document in documents:
                session.execute_write(self._upsert_document, document)
        return len(documents)

    def delete_source(self, source_id: str) -> None:
        logger.info("Neo4jGraphStore.delete_source: {}", source_id)
        with self.driver.session(database=self.database) as session:
            session.run(
                """
                MATCH (d:Destination {source_id: $source_id})
                DETACH DELETE d
                """,
                source_id=source_id,
            )

    @staticmethod
    def _upsert_document(tx: Any, document: SourceDocument) -> None:
        logger.debug("Neo4jGraphStore._upsert_document: source_id={}", document.source_id)
        metadata = dict(document.metadata)
        destination = _destination_name(document)
        tx.run(
            """
            MERGE (d:Destination {source_id: $source_id})
            SET d.title = $title,
                d.destination = $destination,
                d.url = $url,
                d.content = $content,
                d.source_type = $source_type,
                d.page_id = $page_id
            """,
            source_id=document.source_id,
            title=document.title,
            destination=destination,
            url=str(document.url or ""),
            content=document.content,
            source_type=document.source_type,
            page_id=str(metadata.get("page_id") or ""),
        )
        parent = _clean_metadata_text(metadata.get("parent"))
        if parent:
            tx.run(
                """
                MATCH (d:Destination {source_id: $source_id})
                MERGE (p:Destination {destination: $parent})
                SET p.title = coalesce(p.title, $parent)
                MERGE (d)-[:PART_OF]->(p)
                """,
                source_id=document.source_id,
                parent=parent,
            )
        for category in _metadata_list(metadata.get("categories")):
            tx.run(
                """
                MATCH (d:Destination {source_id: $source_id})
                MERGE (c:Category {name: $category})
                MERGE (d)-[:IN_CATEGORY]->(c)
                """,
                source_id=document.source_id,
                category=category,
            )
        for heading in _metadata_list(metadata.get("headings")):
            tx.run(
                """
                MATCH (d:Destination {source_id: $source_id})
                MERGE (s:Section {key: $source_id + ':' + $heading})
                SET s.name = $heading
                MERGE (d)-[:HAS_SECTION]->(s)
                """,
                source_id=document.source_id,
                heading=heading,
            )
        for link in _metadata_list(metadata.get("links"))[:100]:
            tx.run(
                """
                MATCH (d:Destination {source_id: $source_id})
                MERGE (target:Destination {destination: $target})
                SET target.title = coalesce(target.title, $target)
                MERGE (d)-[:LINKS_TO]->(target)
                """,
                source_id=document.source_id,
                target=link,
            )

    def retrieve(self, query: str, top_k: int, method: str = "graph_fulltext") -> list[SourceDocument]:
        logger.info("Neo4jGraphStore.retrieve: method={} top_k={} query_len={}", method, top_k, len(query))
        if method not in GRAPH_METHODS:
            raise ValueError(f"Unsupported graph retrieval method: {method}")
        cypher = _neo4j_retrieval_query(method, self.fulltext_index)
        with self.driver.session(database=self.database) as session:
            records = session.run(cypher, {"query": query, "top_k": top_k}).data()
        results = [_record_to_document(record, method) for record in records]
        logger.debug("Neo4jGraphStore.retrieve: {} results", len(results))
        return results


def _neo4j_retrieval_query(method: str, index_name: str) -> str:
    if method == "graph_neighbors":
        return f"""
        CALL db.index.fulltext.queryNodes('{index_name}', $query) YIELD node, score
        WHERE node.source_id IS NOT NULL
        OPTIONAL MATCH (node)-[:LINKS_TO|PART_OF|IN_CATEGORY]-(neighbor)
        WITH node, score, collect(DISTINCT coalesce(neighbor.title, neighbor.name, neighbor.destination))[0..8] AS neighbors
        RETURN node.source_id AS source_id, node.source_type AS source_type, node.title AS title,
               node.url AS url, node.content AS content, node.destination AS destination,
               score + size(neighbors) * 0.05 AS score, neighbors AS graph_context
        ORDER BY score DESC LIMIT $top_k
        """
    if method == "graph_hierarchy":
        return f"""
        CALL db.index.fulltext.queryNodes('{index_name}', $query) YIELD node, score
        WHERE node.source_id IS NOT NULL
        OPTIONAL MATCH (node)-[:PART_OF*1..4]->(ancestor)
        WITH node, score, collect(DISTINCT ancestor.destination)[0..6] AS ancestors
        RETURN node.source_id AS source_id, node.source_type AS source_type, node.title AS title,
               node.url AS url, node.content AS content, node.destination AS destination,
               score + size(ancestors) * 0.1 AS score, ancestors AS graph_context
        ORDER BY score DESC LIMIT $top_k
        """
    return f"""
    CALL db.index.fulltext.queryNodes('{index_name}', $query) YIELD node, score
    WHERE node.source_id IS NOT NULL
    RETURN node.source_id AS source_id, node.source_type AS source_type, node.title AS title,
           node.url AS url, node.content AS content, node.destination AS destination,
           score AS score, [] AS graph_context
    ORDER BY score DESC LIMIT $top_k
    """


def _record_to_document(record: dict[str, Any], method: str) -> SourceDocument:
    return SourceDocument(
        source_id=record["source_id"],
        source_type=record.get("source_type") or "wikivoyage",
        title=record.get("title") or record.get("destination") or "Graph result",
        url=record.get("url") or None,
        content=record.get("content") or "",
        metadata={
            "destination": record.get("destination"),
            "score": float(record.get("score") or 0.0),
            "graph_score": float(record.get("score") or 0.0),
            "graph_method": method,
            "graph_context": record.get("graph_context") or [],
            "retrieval_source": "graph",
        },
    )


def _destination_name(document: SourceDocument) -> str:
    return str(document.metadata.get("destination") or document.title.replace(" travel guide", "")).strip()


def _metadata_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_metadata_text(item) for item in value if _clean_metadata_text(item)]
    text = _clean_metadata_text(value)
    return [text] if text else []


def _clean_metadata_text(value: Any) -> str:
    return str(value or "").replace("_", " ").strip()
