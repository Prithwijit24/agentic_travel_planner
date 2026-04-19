from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import DayPlan, PlanningRequest, PlanningResponse
from agentic_tour_planner.storage.sqlite_store import SQLitePlanStore


def test_store_saves_and_lists_plans(monkeypatch, tmp_path):
    monkeypatch.setenv("OPERATIONS_DB_PATH", str(tmp_path / "plans.db"))
    get_settings.cache_clear()

    store = SQLitePlanStore()
    request = PlanningRequest(destination="Kyoto", trip_length_days=3)
    response = PlanningResponse(
        overview="A concise trip",
        itinerary=[
            DayPlan(
                day=1,
                theme="Historic center",
                morning=["Visit Kiyomizu-dera"],
                afternoon=["Walk Higashiyama"],
                evening=["Dinner in Gion"],
            )
        ],
        practical_tips=["Book temple tickets early."],
        citations=[],
        insights={
            "route": {
                "strategy": "Cluster sights by district.",
                "cluster_advice": [],
                "transit_notes": [],
            },
            "budget": {
                "estimated_daily_budget": 120.0,
                "estimated_total_budget": 360.0,
                "assumptions": [],
                "saving_tips": [],
            },
            "timing": {
                "season_summary": "Balanced conditions.",
                "booking_window": "Book 4-8 weeks ahead.",
                "day_planning_notes": [],
            },
        },
        model_used="llama3.2",
        provider_used="ollama",
    )

    store.save_plan(request, response)
    plans = store.list_plans(limit=5)

    assert len(plans) == 1
    assert plans[0].destination == "Kyoto"

