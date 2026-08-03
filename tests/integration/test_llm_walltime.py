"""Live wall-time check for the direct-httpx LLM provider.

The point of removing litellm was to kill the 600s hang: a degraded provider
used to eat the full timeout before failing over. This test makes a REAL call
through the provider's own failover chain and asserts the wall time stays
bounded, so a regression in timeout/failover behaviour is caught immediately.

Skipped automatically when no API key is configured.
"""

import asyncio
import time

import pytest

from agentic_tour_planner.llm.hooks import metrics_bus
from agentic_tour_planner.llm.provider import LLMProvider


def _api_key_configured() -> bool:
    provider = LLMProvider()
    return any(provider._api_key_for(p) for p in provider.list_providers())


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _api_key_configured(), reason="no LLM API key configured"),
]


async def _run() -> str:
    provider = LLMProvider()
    return await provider.complete_text(
        'Reply with exactly one word: "pong"',
        role="worker",
    )


def test_real_llm_call_wall_time():
    start = time.perf_counter()
    result = asyncio.run(_run())
    elapsed = time.perf_counter() - start

    print(f"\n[wall-time] LLM call took {elapsed:.2f}s -> {result!r}")
    assert result, "LLM call should return a response"
    # A single completion through the failover chain must never take minutes.
    assert elapsed < 90, f"LLM call took {elapsed:.1f}s; failover timeout is broken"


def test_real_llm_call_recorded_in_metrics():
    metrics_bus.reset()
    asyncio.run(_run())

    summary = metrics_bus.summary()
    print(f"\n[metrics] {summary}")
    assert summary["time"]["calls"] >= 1, "LLM call should be recorded"
    assert summary["time"]["total_llm_s"] > 0
