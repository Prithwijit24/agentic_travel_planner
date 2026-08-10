"""End-to-end pipeline test with real LLM calls."""

import asyncio
import time

from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.pipeline.v2_orchestrator import generate_itinerary


async def main():
    request = PlanningRequest(
        destination="Gangtok",
        trip_length_days=2,
        interests=["monasteries", "food"],
        travelers=2,
        budget_tier="midrange",
    )

    print("=" * 60)
    print("E2E Pipeline Test: Gangtok, 2 days, 2 travelers")
    print("=" * 60)

    start = time.time()
    response = await generate_itinerary(request)
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.1f}s")
    print(f"Plan ID: {response.plan_id}")
    print(f"Provider: {response.provider_used}")
    print(f"Days: {len(response.itinerary)}")

    print(f"\nOverview: {response.overview[:200]}...")

    for day in response.itinerary:
        print(f"\n--- Day {day.day} ({day.theme}) ---")
        if day.summary:
            print(f"  {day.summary[:150]}...")
        for spot in day.spots:
            print(f"  - {spot.name}")

    if response.cost_estimate and response.cost_estimate.overall:
        print(f"\nCost: Rs {response.cost_estimate.overall.grand_total} total, "
              f"Rs {response.cost_estimate.overall.per_person_total} per person")

    if response.practical_tips:
        print(f"\nTips: {len(response.practical_tips)}")
        for tip in response.practical_tips[:3]:
            print(f"  - {tip}")

    print(f"\n{'=' * 60}")
    print(f"TOTAL TIME: {elapsed:.1f}s (target: <60s)")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
