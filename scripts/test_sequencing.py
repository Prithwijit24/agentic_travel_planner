"""Test the deterministic sequencing."""

from __future__ import annotations

from agentic_tour_planner.retrieval.pipeline import retrieve
from agentic_tour_planner.sequencing.bin_packer import sequence

# Get POIs from retrieval
pois = retrieve("Gangtok", ["monasteries", "restaurants"])
print(f"Retrieved {len(pois)} POIs")

# Run sequencing twice to verify determinism
result1 = sequence(pois, duration_days=2)
result2 = sequence(pois, duration_days=2)

print("\n=== Sequencing result (2 days) ===")
for day in result1:
    print(f"Day {day['day']} ({day['city']}):")
    for poi in day["pois"]:
        print(f"  - {poi.get('name', '?')}")

# Verify determinism
assert result1 == result2, "Determinism check failed!"
print("\nDeterminism verified: both runs produced identical output")
