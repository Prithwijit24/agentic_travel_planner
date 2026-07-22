from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.retrieval.hybrid_retriever import HybridRetriever


class FakeVectorStore:
    def retrieve(self, query: str, top_k: int) -> list[SourceDocument]:
        return [
            SourceDocument(
                source_id="vector",
                source_type="wikivoyage",
                title="Vector match",
                content="temple gardens",
                metadata={"score": 0.9},
            ),
            SourceDocument(
                source_id="shared",
                source_type="wikivoyage",
                title="Shared match",
                content="historic district",
                metadata={"score": 0.6},
            ),
        ][:top_k]


class FakeGraphStore:
    def retrieve(self, query: str, top_k: int, method: str = "graph_fulltext") -> list[SourceDocument]:
        return [
            SourceDocument(
                source_id="shared",
                source_type="wikivoyage",
                title="Shared match",
                content="historic district",
                metadata={"graph_score": 4.0, "score": 4.0, "graph_method": method},
            ),
            SourceDocument(
                source_id="graph",
                source_type="wikivoyage",
                title="Graph match",
                content="Kansai hierarchy",
                metadata={"graph_score": 3.0, "score": 3.0, "graph_method": method},
            ),
        ][:top_k]


def test_hybrid_retriever_rrf_combines_vector_and_graph_results():
    retriever = HybridRetriever(vector_store=FakeVectorStore(), graph_store=FakeGraphStore())

    results = retriever.retrieve("Kyoto temples", top_k=3, strategy="rrf", graph_method="graph_hierarchy")

    assert [doc.source_id for doc in results] == ["shared", "vector", "graph"]
    assert results[0].metadata["retrieval_source"] == "hybrid"
    assert results[0].metadata["graph_method"] == "graph_hierarchy"


def test_hybrid_retriever_supports_graph_only_strategy():
    retriever = HybridRetriever(vector_store=FakeVectorStore(), graph_store=FakeGraphStore())

    results = retriever.retrieve("Kyoto temples", top_k=1, strategy="graph_only", graph_method="graph_neighbors")

    assert results[0].source_id == "shared"
    assert results[0].metadata["graph_method"] == "graph_neighbors"
