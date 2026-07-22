from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.retrieval.graph_store import InMemoryGraphStore


def test_in_memory_graph_store_retrieves_hierarchy_matches():
    store = InMemoryGraphStore()
    store.upsert_documents(
        [
            SourceDocument(
                source_id="kyoto",
                source_type="wikivoyage",
                title="Kyoto travel guide",
                content="Historic temples and gardens.",
                metadata={
                    "destination": "Kyoto",
                    "parent": "Kansai",
                    "categories": ["Guide articles"],
                    "links": ["Osaka"],
                    "headings": ["See", "Eat"],
                },
            ),
            SourceDocument(
                source_id="osaka",
                source_type="wikivoyage",
                title="Osaka travel guide",
                content="Food markets and nightlife.",
                metadata={"destination": "Osaka", "parent": "Kansai"},
            ),
        ]
    )

    results = store.retrieve("Kansai temples", top_k=1, method="graph_hierarchy")

    assert results[0].source_id == "kyoto"
    assert results[0].metadata["retrieval_source"] == "graph"
    assert results[0].metadata["graph_method"] == "graph_hierarchy"
    assert results[0].metadata["graph_score"] > 0
