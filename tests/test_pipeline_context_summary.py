"""Test pipeline context_summary property."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline


@pytest.fixture(autouse=True)
def _mock_heavy_deps():
    with (
        patch("agentic_tour_planner.pipeline.agentic_pipeline.HybridRetriever") as mock_retriever_cls,
        patch("agentic_tour_planner.pipeline.agentic_pipeline.rerank_documents", side_effect=lambda _q, d, **_kw: d),
    ):
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []
        mock_retriever_cls.return_value = mock_retriever
        yield


@pytest.mark.asyncio
async def test_context_summary_populated_after_gather():
    pipeline = AgenticTourPlannerPipeline()
    assert pipeline.context_summary is None

    request = PlanningRequest(destination="Kyoto", interests=["temples"], include_live_data=False)

    _ = await pipeline.gather_context(request)

    assert pipeline.context_summary is not None
    assert "documents_count" in pipeline.context_summary
    assert "search_results_count" in pipeline.context_summary
    assert "place_hours_count" in pipeline.context_summary
    assert "weather" in pipeline.context_summary
    assert pipeline.context_summary["documents_count"] >= 0
    assert pipeline.context_summary["search_results_count"] >= 0
