"""Test the LangGraph critique loop."""

import asyncio
import os

from agentic_tour_planner.retrieval.pipeline import retrieve
from agentic_tour_planner.sequencing.bin_packer import sequence
from agentic_tour_planner.agents.graph import run_critique_loop
from agentic_tour_planner.agents.state import TripState


async def main():
    # Check if LLM is available
    has_keys = any(os.environ.get(k) for k in [
        "oraclellm_api_key", "agnes_api_key", "nararouter_api_key", "opencode_api_key"
    ])
    if not has_keys:
        print("SKIP: No LLM API keys configured. Install at least one provider key to test the full loop.")
        return

    # 1. Retrieve POIs
    print("=== Retrieving POIs for Gangtok ===")
    pois = retrieve("Gangtok", ["monasteries", "restaurants"])
    print(f"Retrieved: {len(pois)} POIs")

    # 2. Sequence
    print("\n=== Sequencing ===")
    skeleton = sequence(pois, duration_days=2)
    for day in skeleton:
        print(f"Day {day['day']} ({day['city']}): {len(day['pois'])} POIs")

    # 3. Run critique loop
    print("\n=== Running critique loop ===")
    state = TripState(
        trip_meta={
            "destination": "Gangtok",
            "travelers": 2,
            "budget_tier": "midrange",
            "duration_days": 2,
            "daily_hour_budget": 8.0,
        },
        day_skeleton=skeleton,
        critiques=[],
        revision_count=0,
    )

    result = await run_critique_loop(state)

    print(f"\n=== Results ===")
    print(f"Revisions: {result.get('revision_count', 0)}")
    print(f"Critiques: {len(result.get('critiques', []))}")
    print(f"Known limitations: {len(result.get('known_limitations', []))}")

    if result.get("cost_summary"):
        print(f"Grand total: Rs {result['cost_summary'].get('grand_total', 'N/A')}")
        print(f"Per person: Rs {result['cost_summary'].get('per_person_total', 'N/A')}")

    final_skeleton = result.get("day_skeleton", [])
    print(f"\nFinal skeleton: {len(final_skeleton)} days")
    for day in final_skeleton:
        print(f"  Day {day['day']}: {len(day['pois'])} POIs")


if __name__ == "__main__":
    asyncio.run(main())
