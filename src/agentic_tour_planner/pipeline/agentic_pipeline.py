"""V2 Pipeline wrapper - adapter for the API.

Wraps the new v2 orchestrator and provides the interface the API expects.
"""

from __future__ import annotations

from agentic_tour_planner.api.events import EventEmitter
from agentic_tour_planner.domain.models import DetailedPlan, PlanningRequest, PlanningResponse
from agentic_tour_planner.pipeline.v2_orchestrator import generate_itinerary
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class AgenticTourPlannerPipeline:
    """V2 pipeline that replaces the old multi-pass LLM pipeline."""

    def __init__(self, provider=None) -> None:
        self.provider = provider
        self.context = None
        self.llm_usage = {"used": ["retrieval", "sequencing", "critique"], "fallback": []}
        self.profiler = _SimpleProfiler()

    async def run(
        self,
        request: PlanningRequest,
        context=None,
        insights=None,
        emitter: EventEmitter | None = None,
    ) -> PlanningResponse:
        """Run the v2 pipeline."""
        response = await generate_itinerary(request, emitter=emitter)
        return response

    async def run_detailed_places(
        self,
        request: PlanningRequest,
        response: PlanningResponse,
        insights=None,
    ) -> DetailedPlan | None:
        """Detailed places are now handled in the single-pass narration."""
        return None


class _SimpleProfiler:
    """Minimal profiler replacement."""

    def reset(self):
        pass

    def as_table(self):
        return []
