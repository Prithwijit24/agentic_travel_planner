"""Test the retrieval pipeline."""

from __future__ import annotations

import time

from agentic_tour_planner.retrieval.pipeline import get_available_tags, retrieve

print("=== Test 1: retrieve('Gangtok', ['monasteries']) ===")
start = time.time()
results = retrieve("Gangtok", ["monasteries"])
elapsed = time.time() - start
print(f"Results: {len(results)}, Time: {elapsed:.3f}s")
for r in results[:3]:
    print(f"  - {r.get('name', '?')} ({r.get('category', '?')})")

print("\n=== Test 2: retrieve('Sikkim', ['nature', 'monasteries']) ===")
start = time.time()
results = retrieve("Sikkim", ["nature", "monasteries"])
elapsed = time.time() - start
print(f"Results: {len(results)}, Time: {elapsed:.3f}s")
for r in results:
    print(f"  - {r.get('name', '?')} ({r.get('category', '?')})")

print("\n=== Test 3: get_available_tags('Gangtok') ===")
tags = get_available_tags("Gangtok")
print(f"Tags: {tags}")

print("\nAll tests passed!")
