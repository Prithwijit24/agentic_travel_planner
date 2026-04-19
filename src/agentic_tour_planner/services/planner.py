from __future__ import annotations

from agentic_tour_planner.domain.models import PlanningRequest, PlanningResponse
from agentic_tour_planner.pipeline.agentic_pipeline import AgenticTourPlannerPipeline
from agentic_tour_planner.storage.sqlite_store import SQLitePlanStore


class PlannerService:
    def __init__(self, provider=None) -> None:
        self.pipeline = AgenticTourPlannerPipeline(provider=provider)
        self.store = SQLitePlanStore()

    async def create_plan(self, request: PlanningRequest) -> PlanningResponse:
        response = await self.pipeline.run(request)
        self.store.save_plan(request, response)
        return response

