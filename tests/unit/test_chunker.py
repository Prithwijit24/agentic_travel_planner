from agentic_tour_planner.retrieval.chunker import chunk_text


def test_chunk_text_returns_multiple_chunks():
    text = "a" * 300
    chunks = list(chunk_text(text, chunk_size=100, overlap=20))

    assert len(chunks) == 4
    assert chunks[0] == "a" * 100

