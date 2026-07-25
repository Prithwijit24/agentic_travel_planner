# Unified Output Builder Design

## Goal

Create a shared `build_output` function that both CLI and API use to build the output dictionary, ensuring identical structure and enabling consistent word count enforcement for place descriptions.

## Problem

The CLI and API currently produce different output structures:

**CLI output** (manual dict construction):
- `context` with `documents_count`, `search_results_count`, `place_hours_count`, `weather`
- `insights` with nested `route`, `budget`, `timing`
- `response` with specific fields including `travel_month`, `worker_routing`, `metrics`

**API output** (model_dump):
- `context` from `pipeline.context_summary` (same structure)
- `insights` from `response.insights.model_dump()` (same structure)
- `response` from `response.model_dump()` (includes all PlanningResponse fields)
- Missing: `metrics`, `travel_month`, `worker_routing`

## Solution

### New File: `src/agentic_tour_planner/pipeline/output_builder.py`

Create a shared function with the following signature:

```python
def build_output(
    request: PlanningRequest,
    context: RetrievedContext,
    insights: PlanningInsights,
    response: PlanningResponse,
    detailed: DetailedPlan | None = None,
    pipeline: AgenticTourPlannerPipeline | None = None,
    metrics: dict | None = None,
    profile_rows: list[dict] | None = None,
) -> dict:
```

### Output Structure

The function returns a dictionary with the following structure:

```python
{
    "request": request.model_dump(mode="json"),
    "context": {
        "documents_count": len(context.documents),
        "search_results_count": len(context.search_results),
        "place_hours_count": len(context.place_hours),
        "weather": context.weather.summary if context.weather else None,
    },
    "insights": {
        "route": {
            "strategy": insights.route.strategy,
            "cluster_advice": insights.route.cluster_advice,
            "transit_notes": insights.route.transit_notes,
        },
        "budget": {
            "estimated_daily_budget": insights.budget.estimated_daily_budget,
            "estimated_total_budget": insights.budget.estimated_total_budget,
            "assumptions": insights.budget.assumptions,
            "saving_tips": insights.budget.saving_tips,
        },
        "timing": {
            "season_summary": insights.timing.season_summary,
            "booking_window": insights.timing.booking_window,
            "day_planning_notes": insights.timing.day_planning_notes,
        },
    },
    "response": {
        "plan_id": response.plan_id,
        "overview": response.overview,
        "monthly_weather": response.monthly_weather,
        "travel_month": request.travel_month,
        "transport_options": [t.model_dump() for t in response.transport_options],
        "cost_estimate": response.cost_estimate.model_dump() if response.cost_estimate else None,
        "itinerary": [day.model_dump() for day in response.itinerary],
        "practical_tips": response.practical_tips,
        "citations": [c.model_dump() for c in response.citations],
        "provider_used": response.provider_used,
        "model_used": response.model_used,
        "worker_provider_used": response.worker_provider_used,
        "worker_model_used": response.worker_model_used,
        "live_web_brief": response.live_web_brief.model_dump() if response.live_web_brief else None,
        "worker_routing": pipeline.insights_builder.last_worker_used if pipeline else None,
        "generated_at": response.generated_at,
        "metrics": metrics,
    },
    "detailed": detailed.model_dump() if detailed else None,
    "profile": profile_rows or [],
}
```

### Changes

1. **Create `output_builder.py`** with the shared function
2. **Update `cli/plan.py`** to use the shared function instead of manual dict construction
3. **Update `api/main.py`** to use the shared function instead of manual dict construction
4. **Add word count validation** for place descriptions in detailed places (~200 words)

### Word Count Validation

Add validation in the shared function or in the detailed places prompt to ensure each place description is ~200 words. This can be done by:
- Adding a validation step after detailed places generation
- Including word count instructions in the LLM prompt
- Logging warnings if descriptions are outside the target range

## Testing

Run both CLI and API with the same inputs and verify:
1. Output structures are identical
2. Place descriptions are ~200 words each
3. All fields are present and correctly populated

## Files to Modify

- `src/agentic_tour_planner/pipeline/output_builder.py` (new)
- `src/agentic_tour_planner/cli/plan.py`
- `src/agentic_tour_planner/api/main.py`
