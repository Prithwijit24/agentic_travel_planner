from agentic_tour_planner.domain.models import SourceDocument
from agentic_tour_planner.retrieval.reranker import rerank_documents


def test_reranker_prefers_documents_with_more_query_overlap():
    documents = [
        SourceDocument(
            source_type="web",
            source_id="1",
            title="Nightlife",
            content="bars clubs nightlife music",
        ),
        SourceDocument(
            source_type="web",
            source_id="2",
            title="Temples",
            content="kyoto temple shrine historic temple garden",
        ),
    ]

    ranked = rerank_documents("kyoto temple garden", documents, limit=1)

    assert ranked[0].source_id == "2"
